import asyncio
import os
from msgraph import GraphServiceClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
import json
import pprint
import requests

#_scopes = ["https://graph.microsoft.com/Sites.Read.All/.default"]
_scopes = ["https://graph.microsoft.com/.default"]
_credential = DefaultAzureCredential()
_bearer_token_provider = get_bearer_token_provider(_credential, "https://graph.microsoft.com/.default")
_graph_client = GraphServiceClient(DefaultAzureCredential(), _scopes)
_domain = os.getenv("SHAREPOINT_DOMAIN", "163gc.sharepoint.com")

# az login --scope https://graph.microsoft.com/Sites.Read.All/.default

async def getSiteInfo(path):
  """Get Sharepoint site info based on the name"""
  result = await _graph_client.sites.by_site_id(f'{_domain}/:/sites/{path}').get()
  _id = result.id
  return result

async def getSitePages(site):
  """TODO: Test this method to see what it yields."""
  _id = site.id.split(',')[1]
  print(f"The id used to retreive pages: {_id}")
  result = await _graph_client.sites.by_site_id(_id).pages.get()
  return result

async def getSiteDrive(site, drive_name):
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
    response = await getSiteInfo("DigitalTransformationProcessImprovement")
    drive = await getSiteDrive(response, "Documents")
    getFilesId(drive.id)

def getFilesId(driveId: str):
  headers = {
        'Accept': 'application/json'
  }
  token = _bearer_token_provider()
  headers["Authorization"] = "Bearer " + token
  url = f"https://graph.microsoft.com/v1.0/drives/{driveId}/root/children"#?$select=id,name,@microsoft.graph.downloadUrl"
  print(f"Trying to get drive items from --> {url}")
  r = requests.get(url, headers=headers)
  files = r.json()['value']
  for file in files:
    if '@microsoft.graph.downloadUrl' in file:
      downloadFile(file['@microsoft.graph.downloadUrl'], file['name'])

def downloadFile(url, name):
  with requests.get(url, stream=True) as r:
    r.raise_for_status()
    with open('./temp_download/' + name, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

asyncio.run(main())

# Microsoft Graph API
# 1 get site id:
# https://graph.microsoft.com/v1.0/sites/163gc.sharepoint.com/:/sites/DigitalTransformationProcessImprovement
# {
#     "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#sites/$entity",
#     "@microsoft.graph.tips": "Use $select to choose only the properties your app needs, as this can lead to performance improvements. For example: GET sites('<key>')/microsoft.graph.getByPath(path=<key>)?$select=displayName,error",
#     "createdDateTime": "2020-05-01T18:30:05.5Z",
#     "description": " ",
#     "id": "163gc.sharepoint.com,cd54f759-8deb-420c-9f8c-06dfae0ec237,b279f2bd-ddb4-4248-a74f-4d1a3d3f8852",
#     "lastModifiedDateTime": "2024-10-25T16:45:50Z",
#     "name": "DigitalTransformationProcessImprovement",
#     "webUrl": "https://163gc.sharepoint.com/sites/DigitalTransformationProcessImprovement",
#     "displayName": "Digital Transformation Office - Bureau de la transformation numérique",
#     "root": {},
#     "siteCollection": {
#         "hostname": "163gc.sharepoint.com"
#     }
# }
