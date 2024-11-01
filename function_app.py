import logging
import os
import re

import azure.durable_functions as df
import azure.functions as func
import requests
from azure.durable_functions import (DurableOrchestrationClient,
                                     DurableOrchestrationContext)
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from msgraph import GraphServiceClient

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_scopes = ["https://graph.microsoft.com/.default"]
_credential = DefaultAzureCredential()
_bearer_token_provider = get_bearer_token_provider(_credential,
                                                   "https://graph.microsoft.com/.default")
_graph_client = GraphServiceClient(DefaultAzureCredential(), _scopes)
_domain = os.getenv("SHAREPOINT_DOMAIN", "163gc.sharepoint.com")

@app.route(route="index_sharepoint_site_files", auth_level=func.AuthLevel.FUNCTION)
@app.durable_client_input(client_name="client")
async def index_sharepoint_site_files(req: func.HttpRequest, client: DurableOrchestrationClient) -> func.HttpResponse:
    """
    Main trigger method that reads site files and index them into an Azure Search Service index

    Debug with 'F5' (if you have Azure Function Extension installed, or you can also Ctrl+Shift+P and
    -> Attach: project_name function)
    """
    logging.info('Python HTTP trigger function processed a request.')

    site_name = req.params.get( 'site_name')
    drive_name = req.params.get('drive_name')
    if not site_name or not drive_name:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            site_name = req_body.get('site_name')
            drive_name = req_body.get('drive_name')

    if site_name and drive_name:
        input_data = {
            "site_name": site_name,
            "drive_name": drive_name
        }
        instance_id = await client.start_new("start", None, client_input=input_data)
        return client.create_check_status_response(req, instance_id)
    return func.HttpResponse(body="Unable to start durable function due to missing parameters", status_code=400)

@app.orchestration_trigger(context_name="context")
def start(context: DurableOrchestrationContext):
    """
    Initiate the whole process of loading up a site, fetching site items id and then indexing each one of them.
    """
    files = []
    input_data = context.get_input()
    drive_name = input_data["drive_name"]
    site_name = input_data["site_name"]
    logger.info('Inside Start function of durable method for site -> %s and drive name -> %s', site_name, drive_name)
    site_id = yield context.call_activity("get_site_info", site_name)
    logger.info("Got the site id -> %s", site_id)

    inputs = {
        "site_id": site_id,
        "drive_name": drive_name
    }
    url = yield context.call_activity("get_site_drive_url", inputs)
    if url:
        files = yield context.call_activity("get_files", url)

    return files

@app.activity_trigger(input_name="sitename") # cannot use underscore for bindings, silly regex they have wont allow it
async def get_site_info(sitename: str):
    """
    Get Sharepoint site info based on the name.
        ATM we only return the site.id, that's all we need going on forward.
    """
    url = f'{_domain}/:/sites/{sitename}'
    logger.info("Going to use this url to fetch site id and metadata: %s", url)
    result = await _graph_client.sites.by_site_id(url).get()
    return result.id

@app.activity_trigger(input_name="inputs")
async def get_site_drive_url(inputs):
    """Method used to pass a site and a drive name in order to return the drive id

    Return url to be called for graph API to get the files
    """
    _id = inputs['site_id'].split(',')[1]
    logger.info("The id used to retreive pages: %s", _id)
    # get drives https://graph.microsoft.com/v1.0/sites/{siteid}/drives
    drives = await _graph_client.sites.by_site_id(_id).drives.get()
    filtered_drives = [drive for drive in drives.value if drive.odata_type== "#microsoft.graph.drive"]

    # Here we might receive something like Documents/SubfolderA/Some Other Folder/
    # And we simply want to retreive the drive id for the root folder.
    path_structure = inputs['drive_name'].strip('/').split('/')

    for drive in filtered_drives:
        if drive.name == path_structure[0]:
            logger.info("Found the root drive -> %s.", drive.name)
            # return the list of drives
            drives_info = [{"drive_name": drive.name, "drive_id": drive.id }]
            # return an empty array if the folder path was a single folder, else return the remainder of the path.
            remaining_folders = path_structure[1:] if len(path_structure) > 1 else []
            drives_info.extend({"drive_name": folder, "drive_id": ""} for folder in remaining_folders)
            logger.info("This is the length of the drives return statement: %s", len(drives_info))

    # if we got more than 1 drive we need to drill down the rest of the drives without the
    # graph API Since it doesn't do that sort of recursion.
    if len(drives_info) > 1:
        return get_drives_info(f"https://graph.microsoft.com/v1.0/drives/{drives_info[0]['drive_id']}/root/children",
                               drives_info[1:])
    return f"https://graph.microsoft.com/v1.0/drives/{drives_info[0]['drive_id']}/root/children"

@app.activity_trigger(input_name="url")
async def get_files(url):
    """Should drill down folder to folder until the folders array passed is empty.
    Return array of @microsoft.graph.downloadUrl attribute for each files
    """
    logger.info("Getting files and/or folders. Drive -> %s", url)
    result = call_graph_api(url, attribute_filter="@microsoft.graph.downloadUrl")
    return [file['@microsoft.graph.downloadUrl'] for file in result]

def call_graph_api(url: str, **kwargs):
    """
    Calls the graph API. Would use the client but it doesn't support our use case for drilling down folders *yet*
    """
    odata_filter = kwargs.get('odata_filter', None)
    attribute_filter = kwargs.get('attribute_filter', None)
    headers = {
        'Accept': '*/*',
        "Authorization": f"Bearer {_bearer_token_provider()}"
    }
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    result = r.json()['value']
    if odata_filter:
        result = [item for item in result if item['odata_type'] == odata_filter]
    if attribute_filter:
        result = [item for item in result if attribute_filter in item]
    return result

def get_drives_info(url: str, drives_info):
    """
    Recursive function that will populate the missing drives_id from the list

    Return [{"drive_name": $drive_name, "drive_id": $drive_id}, {...}]
    """
    # this is the base url, we will extend it with /items/{folder_id}/children (removing /root)
    # for each items in the list
    result = call_graph_api(url, attribute_filter="folder")#, odata_filter="#microsoft.graph.drive")
    new_url = url.rstrip("/root/children") # remove the root/children if present
    pattern = r'(/items).*'
    new_url = re.sub(pattern, r'\1', new_url).rstrip("/items")
    for folder in result:
        if folder['name'] == drives_info[0]["drive_name"]:
            new_url = new_url + f"/items/{folder['id']}/children"
    logger.info("---> New url ---> %s", new_url)
    if len(drives_info) > 1:
        return get_drives_info(new_url, drives_info[1:])
    return new_url

# def _download_file(url, name):
#     """Download file to filesystem"""
#     with requests.get(url, stream=True, timeout=10) as r:
#         r.raise_for_status()
#         with open('./temp_download/' + name, 'wb') as f:
#             for chunk in r.iter_content(chunk_size=8192):
#                 f.write(chunk)
