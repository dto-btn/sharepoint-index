# sharepoint-index

Azure Function http trigger that will be triggered and passed a Sharepoint site `name` and a drive `name` to pull 
files from and index.

## Developpers

Pre-requisite:
* Install recommended extensions in VS Code (such as `pylint`, etc.)
* Install [Azure Function Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local?tabs=linux%2Cisolated-process%2Cnode-v4%2Cpython-v2%2Chttp-trigger%2Ccontainer-apps&pivots=programming-language-python#install-the-azure-functions-core-tools)

### Az CLI

In order to run this project locally you need Az CLI installed and to be logged in the sub you will be using the
resources from. You also need to ensure you are logged with the proper scopes.

```bash
# examples:
az login --scope https://graph.microsoft.com/Sites.Read.All/.default
# or 
az login --scope https://graph.microsoft.com/.default
```