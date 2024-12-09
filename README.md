# sharepoint-index

Azure Function http trigger that will be triggered and passed a Sharepoint site `name` and a drive `name` to pull 
files from and index.

## Developpers

Pre-requisite:
* Install recommended extensions in VS Code (such as `pylint`, etc.)
* Install [Azure Function Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local?tabs=linux%2Cisolated-process%2Cnode-v4%2Cpython-v2%2Chttp-trigger%2Ccontainer-apps&pivots=programming-language-python#install-the-azure-functions-core-tools)

Create your python env: 

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Invoke the Az Func locally

Debug with `F5` and then simply use postman/curl to reach the application:

```bash
curl --location --request GET 'http://localhost:7071/api/index_sharepoint_site_files' \
--header 'Content-Type: application/json' \
--data '{
    "site_name": "DigitalTransformationProcessImprovement",
    "drive_name": "Documents/Emerging Concepts and Technologies/SSC Assistant"
}'
```

### Az CLI

In order to run this project locally you need Az CLI installed and to be logged in the sub you will be using the
resources from. You also need to ensure you are logged with the proper scopes.

```bash
# examples:
az login --scope https://graph.microsoft.com/Sites.Read.All/.default
# or 
az login --scope https://graph.microsoft.com/.default
```

### Running the Az Function

Ensure you have a `local.settings.json` file present inside the `sharepoint_indexer` folder that contains:

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsFeatureFlags": "EnableWorkerIndexing",
    "AzureWebJobsStorage": "<connection-string>"
  }
}
```

## How-to

This Azure Function was init via the Azure Core Tools: 

```bash
func init sharepoint_indexer --worker-runtime python --model V2
func new --template "Http Trigger" --name index_sharepoint_site_files
```

## Documentation

* Azure function `host.json` [documentation](https://learn.microsoft.com/en-us/azure/azure-functions/functions-host-json)
  * `local.settings.json` [documentation](https://learn.microsoft.com/en-us/azure/azure-functions/functions-develop-local#local-settings-file)
* Microsoft graph API, direct access to site id: https://163dev.sharepoint.com/sites/AssistantHome/_api/site/id
  * just append `_api/site/id`, [some documentation on the using this method](https://marczak.io/posts/2023/01/sharepoint-graph-and-azure-sp/)