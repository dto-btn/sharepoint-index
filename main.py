import asyncio
import os
from msgraph import GraphServiceClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
import requests
import logging

logging.

#_scopes = ["https://graph.microsoft.com/Sites.Read.All/.default"]
_scopes = ["https://graph.microsoft.com/.default"]
_credential = DefaultAzureCredential()
_bearer_token_provider = get_bearer_token_provider(_credential,
                                                   "https://graph.microsoft.com/.default")
_graph_client = GraphServiceClient(DefaultAzureCredential(), _scopes)
_domain = os.getenv("SHAREPOINT_DOMAIN", "163gc.sharepoint.com")

async def get_site_info(path):
    """Get Sharepoint site info based on the name"""
    result = await _graph_client.sites.by_site_id(f'{_domain}/:/sites/{path}').get()
    _id = result.id
    return result

async def get_site_page(site):
    """TODO: Test this method to see what it yields."""
    _id = site.id.split(',')[1]
    print(f"The id used to retreive pages: {_id}")
    result = await _graph_client.sites.by_site_id(_id).pages.get()
    return result

async def get_site_drive(site, drive_name):
    """Method used to pass a site and a drive name in order to return the Drive instance"""
    _id = site.id.split(',')[1]
    print(f"The id used to retreive pages: {_id}")
    # get drives https://graph.microsoft.com/v1.0/sites/{siteid}/drives
    result = await _graph_client.sites.by_site_id(_id).drives.get()
    filtered_drives = [drive for drive in result.value if drive.odata_type== "#microsoft.graph.drive"]
    for drive in filtered_drives:
        if drive.name == drive_name:
            return drive
    return None

async def main():
    """TODO: Convert this to an Azure Function entry point"""
    response = await get_site_info("DigitalTransformationProcessImprovement")
    drive = await get_site_drive(response, "Documents")
    get_files_id(drive.id)

def get_files_id(drive_id: str):
    """
    Get files id for each of the item within the drive passed in parameter.
    Will also download the files directly to FS
    """
    headers = {
            'Accept': 'application/json'
    }
    token = _bearer_token_provider()
    headers["Authorization"] = "Bearer " + token
    # Can also use odata filter -> ?$select=id,name,@microsoft.graph.downloadUrl"
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
    print(f"Trying to get drive items from --> {url}")
    r = requests.get(url, headers=headers, timeout=10)
    files = r.json()['value']
    for file in files:
        if '@microsoft.graph.downloadUrl' in file:
            download_file(file['@microsoft.graph.downloadUrl'], file['name'])

def download_file(url, name):
    """Download file to filesystem"""
    with requests.get(url, stream=True, timeout=10) as r:
        r.raise_for_status()
        with open('./temp_download/' + name, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

asyncio.run(main())
