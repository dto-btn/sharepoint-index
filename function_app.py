import json
import logging
import os

import azure.functions as func
import azure.durable_functions as df
import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.durable_functions import DurableOrchestrationClient, DurableOrchestrationContext
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
    else:
        return func.HttpResponse(body="Unable to start durable function due to missing parameters", status_code=400)

@app.orchestration_trigger(context_name="context")
def start(context: DurableOrchestrationContext):
    """
    Initiate the whole process of loading up a site, fetching site items id and then indexing each one of them.
    """
    input_data = context.get_input()
    drive_name = input_data["drive_name"]
    site_name = input_data["site_name"]
    logging.info('Inside Start function of durable method for site -> %s and drive name -> %s', site_name, drive_name)
    site_id = yield context.call_activity("get_site_info", site_name)
    inputs = {
        "site_id": site_id,
        "drive_name": drive_name
    }
    drive_info = yield context.call_activity("get_site_drive", inputs)

    return [site_name, drive_name, site_id]

@app.activity_trigger(input_name="sitename") # cannot use underscore for bindings, silly regex they have wont allow it
async def get_site_info(sitename: str):
    """
    Get Sharepoint site info based on the name.
        ATM we only return the site.id, that's all we need going on forward.
    """
    url = f'{_domain}/:/sites/{sitename}'
    logger.debug("Going to use this url to fetch site id and metadata: %s", url)
    result = await _graph_client.sites.by_site_id(url).get()
    logger.debug(result)
    return result.id

@app.activity_trigger(input_name="inputs")
async def get_site_drive(inputs):
    """Method used to pass a site and a drive name in order to return the Drive instance"""
    _id = inputs['site_id'].split(',')[1]
    logger.debug("The id used to retreive pages: %s", _id)
    # get drives https://graph.microsoft.com/v1.0/sites/{siteid}/drives
    result = await _graph_client.sites.by_site_id(_id).drives.get()
    filtered_drives = [drive for drive in result.value if drive.odata_type== "#microsoft.graph.drive"]
    for drive in filtered_drives:
        logger.debug(drive)
        if drive.name == inputs['drive_name']:
            logging.debug("Found the drive.")
            return drive
    return None

# async def _get_site_page(site):
#     """TODO: Test this method to see what it yields."""
#     _id = site.id.split(',')[1]
#     logger.debug("The id used to retreive pages: %s", _id)
#     result = await _graph_client.sites.by_site_id(_id).pages.get()
#     return result

# def _get_files_id(drive_id: str):
#     """
#     Get files id for each of the item within the drive passed in parameter.
#     Will also download the files directly to FS
#     """
#     headers = {
#         'Accept': 'application/json'
#         "Bearer " + _bearer_token_provider()
#     }
#     # Can also use odata filter -> ?$select=id,name,@microsoft.graph.downloadUrl"
#     url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
#     logger.debug("Trying to get drive items from --> %s", url)
#     r = requests.get(url, headers=headers, timeout=10)
#     files = r.json()['value']
#     for file in files:
#         if '@microsoft.graph.downloadUrl' in file:
#             _download_file(file['@microsoft.graph.downloadUrl'], file['name'])

# def _download_file(url, name):
#     """Download file to filesystem"""
#     with requests.get(url, stream=True, timeout=10) as r:
#         r.raise_for_status()
#         with open('./temp_download/' + name, 'wb') as f:
#             for chunk in r.iter_content(chunk_size=8192):
#                 f.write(chunk)
