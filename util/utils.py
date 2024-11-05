import logging
import re
import os

import requests

from dotenv import load_dotenv
from azure.search.documents.indexes import SearchIndexClient
from llama_index.vector_stores.azureaisearch import AzureAISearchVectorStore
from llama_index.vector_stores.azureaisearch import IndexManagement

load_dotenv()
#azure_openai_uri: str   = os.getenv("AZURE_OPENAI_ENDPOINT", "UNDEFINED")
#api_key: str            = os.getenv("AZURE_OPENAI_API_KEY", "UNDEFINED")
#api_version: str        = os.getenv("AZURE_OPENAI_VERSION", "2024-05-01-preview")
api_search_version: str = os.getenv("AZURE_SEARCH_VERSION", "2024-05-01-preview")
service_endpoint: str   = os.getenv("AZURE_SEARCH_SERVICE_ENDPOINT", "UNDEFINED")
#key: str                = os.getenv("AZURE_SEARCH_ADMIN_KEY", "UNDEFINED")
#alias_index_name: str   = os.getenv("ALIAS_INDEX_NAME", "current")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

__all__ = ["call_graph_api", "get_drives_info", "get_vector_store", "file_metadata"]

_METADATA_FIELDS = {
        'url': '@microsoft.graph.downloadUrl',
        'name': 'name',
        'webUrl': 'webUrl',
        'id': 'id',
        'lastModifiedDateTime': 'lastModifiedDateTime'
    }

def call_graph_api(url: str, token: str, **kwargs):
    """
    Calls the graph API. Would use the client but it doesn't support our use case for drilling down folders *yet*
    """
    odata_filter = kwargs.get('odata_filter', None)
    attribute_filter = kwargs.get('attribute_filter', None)
    headers = {
        'Accept': '*/*',
        "Authorization": f"Bearer {token}"
    }
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    result = r.json()['value']
    if odata_filter:
        result = [item for item in result if item['odata_type'] == odata_filter]
    if attribute_filter:
        result = [item for item in result if attribute_filter in item]
    return result

def get_drives_info(url: str, token: str, drives_info):
    """
    Recursive function that will populate the missing drives_id from the list

    Return [{"drive_name": $drive_name, "drive_id": $drive_id}, {...}]
    """
    # this is the base url, we will extend it with /items/{folder_id}/children (removing /root)
    # for each items in the list
    result = call_graph_api(url, token, attribute_filter="folder")#, odata_filter="#microsoft.graph.drive")
    new_url = url.rstrip("/root/children") # remove the root/children if present
    pattern = r'(/items).*'
    new_url = re.sub(pattern, r'\1', new_url).rstrip("/items")
    for folder in result:
        if folder['name'] == drives_info[0]["drive_name"]:
            new_url = new_url + f"/items/{folder['id']}/children"
    logger.info("---> New url ---> %s", new_url)
    if len(drives_info) > 1:
        return get_drives_info(new_url, token, drives_info[1:])
    return new_url

def get_vector_store(index_name: str, creds):
    """
    Create or re-use index passed in and returns vector store tied to it.
    """
    logger.info("Using search service endpoint: %s", service_endpoint)
    index_client = SearchIndexClient(
        endpoint=service_endpoint,
        credential=creds,
        api_version=api_search_version
    )

    vector_store = AzureAISearchVectorStore(
        search_or_index_client=index_client,
        filterable_metadata_field_keys=_METADATA_FIELDS,
        index_name=index_name.lower(),
        index_management=IndexManagement.CREATE_IF_NOT_EXISTS,
        id_field_key="id",
        chunk_field_key="chunk",
        embedding_field_key="embedding",
        embedding_dimensionality=1536,
        metadata_string_field_key="metadata",
        doc_id_field_key="doc_id",
        language_analyzer="en.lucene",
        vector_algorithm_type="exhaustiveKnn",
        # compression_type="binary" # Option to use "scalar" or "binary". NOTE: compression is only supported for HNSW
    )

    return vector_store

def file_metadata(filename: str):
    """pre-populate metadata with filename for later."""
    metadata = _METADATA_FIELDS.copy()
    metadata['name'] = filename
    return metadata
