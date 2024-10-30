import logging
import os

import azure.functions as func
import azure.durable_functions as df
import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.durable_functions import DurableOrchestrationClient
from msgraph import GraphServiceClient

#app = func.FunctionApp()
app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

#_scopes = ["https://graph.microsoft.com/Sites.Read.All/.default"]
_scopes = ["https://graph.microsoft.com/.default"]
_credential = DefaultAzureCredential()
_bearer_token_provider = get_bearer_token_provider(_credential,
                                                   "https://graph.microsoft.com/.default")
_graph_client = GraphServiceClient(DefaultAzureCredential(), _scopes)

_domain = os.getenv("SHAREPOINT_DOMAIN", "163gc.sharepoint.com")

# Durable function that fetches all sscplus page IDs/pages and uploads them
# @app.route(route="orchestrators/{functionName}")
# @app.durable_client_input(client_name="client")
# async def http_start(req: func.HttpRequest, client):
#     function_name = req.route_params.get('functionName')
#     instance_id = await client.start_new(function_name)
#     response = client.create_check_status_response(req, instance_id)
#     return response

# # timer triggered function to fetch index data, runs Sat at midnight
# # cron with 6 args, the first one being seconds.
# @app.schedule(schedule="0 0 4 * * Fri", arg_name="myTimer", run_on_startup=False, use_monitor=False)
# @app.durable_client_input(client_name="client")
# async def fetch_index_timer_trigger(myTimer: func.TimerRequest, client) -> None:
#     instance_id = await client.start_new("fetch_index_data")
#     logging.info("fetch index timer trigger function executed")

@app.route(route="index_sharepoint_site_files", auth_level=func.AuthLevel.FUNCTION)
@app.durable_client_input(client_name="client")
async def index_sharepoint_site_files(req: func.HttpRequest, client: DurableOrchestrationClient) -> func.HttpResponse:
    """
    Main trigger method that reads site files and index them into an Azure Search Service index

    Debug with 'F5' (if you have Azure Function Extension installed, or you can also Ctrl+Shift+P and 
    -> Attach: project_name function)
    """
    logging.info('Python HTTP trigger function processed a request.')

    site_name = req.params.get('site_name')
    lib_name = req.params.get('lib_name')
    if not site_name or not lib_name:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            site_name = req_body.get('site_name')
            lib_name = req_body.get('lib_name')

    if site_name and lib_name:
        instance_id = await client.start_new("start", site_name, lib_name)
        return client.create_check_status_response(req, instance_id)
    else:
        return func.HttpResponse(body="Unable to start durable function due to missing parameters", status_code=400)

async def start(site_name: str, lib_name: str):
    """
    Initiate the whole process of loading up a site, fetching site items id and then indexing each one of them.
    """
    logging.info('Inside Start function of durable method')

async def _get_site_info(path):
    """Get Sharepoint site info based on the name"""
    result = await _graph_client.sites.by_site_id(f'{_domain}/:/sites/{path}').get()
    return result

async def _get_site_page(site):
    """TODO: Test this method to see what it yields."""
    _id = site.id.split(',')[1]
    logger.debug("The id used to retreive pages: %s", _id)
    result = await _graph_client.sites.by_site_id(_id).pages.get()
    return result

async def _get_site_drive(site, drive_name):
    """Method used to pass a site and a drive name in order to return the Drive instance"""
    _id = site.id.split(',')[1]
    logger.debug("The id used to retreive pages: %s", _id)
    # get drives https://graph.microsoft.com/v1.0/sites/{siteid}/drives
    result = await _graph_client.sites.by_site_id(_id).drives.get()
    filtered_drives = [drive for drive in result.value if drive.odata_type== "#microsoft.graph.drive"]
    for drive in filtered_drives:
        if drive.name == drive_name:
            return drive
    return None

def _get_files_id(drive_id: str):
    """
    Get files id for each of the item within the drive passed in parameter.
    Will also download the files directly to FS
    """
    headers = {
        'Accept': 'application/json'
        "Bearer " + _bearer_token_provider()
    }
    # Can also use odata filter -> ?$select=id,name,@microsoft.graph.downloadUrl"
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
    logger.debug("Trying to get drive items from --> %s", url)
    r = requests.get(url, headers=headers, timeout=10)
    files = r.json()['value']
    for file in files:
        if '@microsoft.graph.downloadUrl' in file:
            _download_file(file['@microsoft.graph.downloadUrl'], file['name'])

def _download_file(url, name):
    """Download file to filesystem"""
    with requests.get(url, stream=True, timeout=10) as r:
        r.raise_for_status()
        with open('./temp_download/' + name, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
