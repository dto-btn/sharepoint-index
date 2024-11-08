import logging
import os
import tempfile
import uuid
from http.client import HTTPException

import azure.durable_functions as df
import azure.functions as func
import requests
from azure.durable_functions import (DurableOrchestrationClient,
                                     DurableOrchestrationContext)
from azure.identity import (DefaultAzureCredential, ManagedIdentityCredential,
                            get_bearer_token_provider)
from llama_index.core import SimpleDirectoryReader
from msgraph import GraphServiceClient

from util import utils

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_DL_DIRECTORY = "sharepoint_indexer"

_scopes = ["https://graph.microsoft.com/.default"]
# Determine the appropriate credential to use
azure_client_id: str    = os.getenv("AZURE_CLIENT_ID")

if azure_client_id:
    _credential = ManagedIdentityCredential(client_id=azure_client_id)
    logger.info("Loading up ManagedIdentityCredential")
else:
    _credential = DefaultAzureCredential()
    logger.info("Loading up DefaultAzureCredential")
_bearer_token_provider = get_bearer_token_provider(_credential,
                                                   "https://graph.microsoft.com/.default")
_graph_client = GraphServiceClient(_credential, _scopes)
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
            "drive_name": drive_name,
            "run_id": str(uuid.uuid4())
        }
        instance_id = await client.start_new("start", None, client_input=input_data)
        logger.info("Started orchestration with ID = %s", instance_id)
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
    run_id = input_data["run_id"]
    logger.info('Inside Start function of durable method for site -> %s and drive name -> %s (runId: %s)',
                site_name,
                drive_name,
                run_id)
    site_id = yield context.call_activity("get_sharepoint_site_info", site_name)
    logger.info("Got the site id -> %s", site_id)

    inputs = {
        "site_id": site_id,
        "drive_name": drive_name
    }
    url = yield context.call_activity("get_site_drive_url", inputs)
    if url:
        files = yield context.call_activity("get_files", url)
        logger.info("Got the files from the requested drive, files contained --> %s", len(files))
        for file in files:
            downloaded = yield context.call_activity("download_file", {'file':file, 'run_id': run_id})
            logger.info("File downloaded successfully? -> %s", downloaded)
            file['downloaded'] = downloaded
        # Index files downloaded.
        result = yield context.call_activity("index_file", {'files':files, 'run_id': run_id, 'site_name': site_name})

    return files

@app.activity_trigger(input_name="sitename") # cannot use underscore for bindings, silly regex they have wont allow it
async def get_sharepoint_site_info(sitename: str):
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
        return utils.get_drives_info(
            f"https://graph.microsoft.com/v1.0/drives/{drives_info[0]['drive_id']}/root/children",
            _bearer_token_provider(),
            drives_info[1:])
    return f"https://graph.microsoft.com/v1.0/drives/{drives_info[0]['drive_id']}/root/children"

@app.activity_trigger(input_name="url")
async def get_files(url):
    """Should drill down folder to folder until the folders array passed is empty.

    Returns
    ----------- 
    Dict array {
                'url': '@microsoft.graph.downloadUrl',
                'name': 'name',
                'webUrl': 'webUrl',
                'id': 'id',
                'lastModifiedDateTime': 'lastModifiedDateTime'
            } for each files
    """
    logger.info("Getting files and/or folders. Drive -> %s", url)
    result = utils.call_graph_api(url, _bearer_token_provider(), attribute_filter="@microsoft.graph.downloadUrl")
    return [{
                'url': file['@microsoft.graph.downloadUrl'],
                'name': file['name'],
                'webUrl': file['webUrl'],
                'id': file['id'],
                'lastModifiedDateTime': file['lastModifiedDateTime']
            } for file in result]

@app.activity_trigger(input_name="inputs")
def download_file(inputs):
    """Download file to filesystem"""
    url = inputs['file']['url']
    name = inputs['file']['name']

    run_id = inputs['run_id']

    path = os.path.join(tempfile.gettempdir(), _DL_DIRECTORY, run_id)
    if not os.path.exists(path):
        os.makedirs(path)
    try:
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            with open(os.path.join(path, name), 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except HTTPException as e:
        logger.error("Unable to download file -> %s, %s", name, e)
        return False
    except OSError as e:
        logger.error("Unable to write file -> %s, %s", name, e)
        return False


@app.activity_trigger(input_name="inputs")
def index_file(inputs):
    """Loads all file from a specific folder and index them in a Azure Search Service"""
    logger.info('Indexing file!')
    files = inputs['files']
    run_id = inputs['run_id']
    site_name = inputs['site_name']
    path = os.path.join(tempfile.gettempdir(), _DL_DIRECTORY, run_id)

    documents = SimpleDirectoryReader(path, file_metadata=utils.file_metadata).load_data()
    logger.info("Loaded document from SimpleDirectoryReader, %s document(s) loaded", len(documents))

    # populate metadata
    for document in documents:
        # match a file (from input) and populate the metadata
        #logger.info("Current document processed: %s", document.metadata['name'])
        file_metadata = [file for file in files if file['name'] == document.metadata['name']]
        if file_metadata:
            document.metadata = file_metadata[0] # there should only be 1 file matching that name.

    # create the index if it doesn't exists, otherwise just populate it for now.
    # overwrite documents if metadata date is newer.
    index = utils.save_index(site_name, documents)
    return index.index_id
