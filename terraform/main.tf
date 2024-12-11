/****************************************************
*                       RG                          *
*****************************************************/
resource "azurerm_resource_group" "main" {
  name     = "${var.name_prefix}${var.project_name}-rg"
  location = var.default_location
}

resource "azurerm_user_assigned_identity" "main" {
  name                = "ssc-assistant-sharepoint-indexer"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
}

resource "azurerm_storage_account" "main" {
  name                     = "${replace(var.project_name, "_", "")}sto"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_container" "sharepoint_az_func" {
  name                 = "sharepoint-az-func"
  storage_account_name = azurerm_storage_account.main.name
}

resource "azurerm_application_insights" "functions" {
  name                = "functions-app-insights"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
}

resource "azurerm_service_plan" "functions" {
  name                = "functions-app-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "P1v3"
}

resource "azurerm_linux_function_app" "functions" {
  name                = "assistant-sharepoint-indexer"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  storage_account_name       = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key
  service_plan_id            = azurerm_service_plan.functions.id

  site_config {
    always_on = true
    vnet_route_all_enabled = true
    application_insights_key = azurerm_application_insights.functions.instrumentation_key
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = {
    "AzureWebJobsFeatureFlags"       = "EnableWorkerIndexing"
    "BUILD_FLAGS"                    = "UseExpressBuild"
    "ENABLE_ORYX_BUILD"              = "true"
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "1"
    "XDG_CACHE_HOME"                 = "/tmp/.cache"
    "BLOB_CONNECTION_STRING"         = azurerm_storage_account.main.primary_connection_string
    "BLOB_CONTAINER_NAME"            = azurerm_storage_container.sharepoint_az_func.name
    "AZURE_SEARCH_SERVICE_ENDPOINT"  = "https://${data.azurerm_search_service.main.name}.search.windows.net"
    "AZURE_SEARCH_ADMIN_KEY"         = data.azurerm_search_service.main.primary_key
    "AZURE_OPENAI_ENDPOINT"          = data.azurerm_cognitive_account.ai.endpoint
    "AZURE_OPENAI_API_KEY"           = data.azurerm_cognitive_account.ai.primary_access_key
    "AZURE_CLIENT_ID"                = azurerm_user_assigned_identity.main.client_id
  }

  identity {
    type = "UserAssigned"
    identity_ids = [ azurerm_user_assigned_identity.main.id ]
  }

  sticky_settings { # settings that are the same regardless of deployment slot..
    app_setting_names = [ "AZURE_SEARCH_SERVICE_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_SEARCH_ADMIN_KEY", "BLOB_CONNECTION_STRING", "BLOB_CONTAINER_NAME", "AZURE_CLIENT_ID" ]
  }

  #virtual_network_subnet_id = data.azurerm_subnet.subscription-vnet-sub.id
}

resource "azurerm_service_plan" "main" {
  name                = "${var.name_prefix}${var.project_name}-plan"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku_name = "WS1"
  os_type = "Windows"
}

resource "azurerm_logic_app_standard" "main" {
  name                       = "${replace(var.project_name, "_", "-")}-logic-app"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  app_service_plan_id        = azurerm_service_plan.main.id
  storage_account_name       = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key
  version = "~4"

  identity {
    type = "SystemAssigned"
  }
  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME" = "dotnet"
  }
}

data "azurerm_managed_api" "sharepoint" {
  name     = "sharepointonline"
  location = var.default_location
}

resource "azurerm_api_connection" "sharepoint" {
    name = "sharepoint-api-connection"
    resource_group_name = azurerm_resource_group.main.name
    managed_api_id = data.azurerm_managed_api.sharepoint.id
}