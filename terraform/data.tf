/****************************************************
*                     OpenAI                        *
*****************************************************/
data "azurerm_resource_group" "ai" {
  name = var.openai_rg
}

data "azurerm_cognitive_account" "ai" {
  name                = var.openai_name
  resource_group_name = var.openai_rg
  //kind = "OpenAI"
}

/****************************************************
*                  Search Services                  *
*****************************************************/
data "azurerm_search_service" "main" {
  name                = "ssc-assistant-dev-search-service"
  resource_group_name = "ScSc-CIO_ECT_ssc_assistant_dev-rg"
}