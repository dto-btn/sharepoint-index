import asyncio
import os
from msgraph import GraphServiceClient
from azure.identity import DefaultAzureCredential
import json
import pprint

#_scopes = ["https://graph.microsoft.com/Sites.Read.All/.default"]
_scopes = ["https://graph.microsoft.com/.default"]
_graph_client = GraphServiceClient(DefaultAzureCredential(), _scopes)
_domain = os.getenv("SHAREPOINT_DOMAIN", "163gc.sharepoint.com")

# az login --scope https://graph.microsoft.com/Sites.Read.All/.default

async def getSiteInfo(path):
  # result = await graph_client.sites.by_site_id('cd54f759-8deb-420c-9f8c-06dfae0ec237,b279f2bd-ddb4-4248-a74f-4d1a3d3f8852').pages.get()
  result = await _graph_client.sites.by_site_id(f'{_domain}/:/sites/{path}').get()
  _id = result.id
  print(_id)
  return result

async def getSitePages(site):
  _id = site.id.split(',')[1]
  print(f"The id used to retreive pages: {_id}")
  result = await _graph_client.sites.by_site_id(_id).pages.get()
  print(result)
  return result

async def getSiteDrive(site, drive_name):
  _id = site.id.split(',')[1]
  print(f"The id used to retreive pages: {_id}")
  result = await _graph_client.sites.by_site_id(_id).drives.get()
  filtered_drives = [drive for drive in result.value if drive.odata_type== "#microsoft.graph.drive"]
  for drive in filtered_drives:
     if drive.name == drive_name:
      print(drive)
      result = await _graph_client.drives.by_drive_id(_id).items.by_drive_item_id(drive.id).children.get()
      print(result)
      # for item in drive.items:
      #     print(f"Item Name: {item.name}")
      # return drive
  return None

async def downloadFileFromDrive(drive, item_id):
  item = await _graph_client.drives.by_drive_id(drive.id).items.by_drive_item_id(item_id).get()
  print(item.name)

async def main():
    response = await getSiteInfo("DigitalTransformationProcessImprovement")
    drive = await getSiteDrive(response, "Documents")
    #await downloadFileFromDrive(drive)

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
