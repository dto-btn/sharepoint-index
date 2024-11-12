import logging
import os
import re
from datetime import datetime as dt

import requests
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.settings import Settings
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.vector_stores.azureaisearch import (AzureAISearchVectorStore,
                                                     IndexManagement)

load_dotenv()

azure_openai_uri: str   = os.getenv("AZURE_OPENAI_ENDPOINT", "UNDEFINED")
api_key: str            = os.getenv("AZURE_OPENAI_API_KEY", "UNDEFINED")
api_version: str        = os.getenv("AZURE_OPENAI_VERSION", "2024-05-01-preview")

service_endpoint: str   = os.getenv("AZURE_SEARCH_SERVICE_ENDPOINT", "UNDEFINED")
search_key: str          = os.getenv("AZURE_SEARCH_ADMIN_KEY", "UNDEFINED")
api_search_version: str = os.getenv("AZURE_SEARCH_VERSION", "2024-05-01-preview")
search_key_credential = AzureKeyCredential(search_key)

index_client = SearchIndexClient(
        endpoint=service_endpoint,
        credential=search_key_credential,
        api_version=api_search_version
    )

openai_model: str = "gpt-35-turbo"
embedding_model: str = "text-embedding-ada-002"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

__all__ = ["call_graph_api", "get_drives_info", "save_index", "file_metadata"]

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

def save_index(index_name: str, documents):
    """
    Create or re-use index passed in and returns vector store tied to it.
    """
    logger.info("Using search service endpoint: %s", service_endpoint)

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

    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    llm = AzureOpenAI(
        model=openai_model,
        deployment_name=openai_model,
        api_version=api_version,
        azure_endpoint=azure_openai_uri,
        api_key=api_key
    )

    embed_model = AzureOpenAIEmbedding(
        model=embedding_model,
        deployment_name=embedding_model,
        api_key=api_key,
        azure_endpoint=str(azure_openai_uri),
        api_version=api_version
    )

    Settings.llm = llm
    Settings.embed_model = embed_model

    parsed_documents = []
    for document in documents:
        needs_update = is_an_updated_document(index_name, document)
        if needs_update:
            parsed_documents.append(document)
            delete_document(index_name=index_name, document=document)

    index = VectorStoreIndex.from_documents(
        parsed_documents, storage_context=storage_context
    )

    return index

def file_metadata(filename: str):
    """pre-populate metadata with filename for later."""
    metadata = _METADATA_FIELDS.copy()
    # process the filename to remove the folders (if any)
    metadata['name'] = os.path.basename(filename)
    return metadata

def is_an_updated_document(index_name: str, document):
    """
    Search for documents in the specified index by their title and return the documents along with their timestamps.
    """
    search_client = SearchClient(
        endpoint=service_endpoint,
        index_name=index_name.lower(),
        credential=search_key_credential
    )

    search_query = f"name eq '{document.metadata['name']}'"
    logger.info(search_query)

    results = search_client.search(
        search_text="*",  # Use wildcard to search for all documents
        filter=search_query,
        select=["name", "lastModifiedDateTime"]  # Specify the fields to retrieve
    )

    if results.get_count() is None or results.get_count() is 0:
        logger.info("No result(s) found, will need to update/insert document")
        return True

    for result in results:
        try:
            date_searched = dt.strptime(result['lastModifiedDateTime'], "%Y-%m-%dT%H:%M:%SZ")
            date_passed = dt.strptime(document.metadata['lastModifiedDateTime'], "%Y-%m-%dT%H:%M:%SZ")
            logger.info("The file %s and the passed date %s and the search service returned date %s",
                        document.metadata['name'],
                        date_passed, date_searched)
            if date_passed > date_searched:
                logger.info("Newer document detected")
                return True
        except ValueError:
            logger.warning("Unable to format date, will skip this entry")
    return False

def delete_document(index_name: str, document):
    """
    Delete documents that match this name from the index passed in parameter
    """
    search_client = SearchClient(
        endpoint=service_endpoint,
        index_name=index_name.lower(),
        credential=search_key_credential
    )

    search_query = f"name eq '{document.metadata['name']}'"
    logger.info(search_query)

    results = search_client.search(
        search_text="*",  # Use wildcard to search for all documents
        filter=search_query,
        select=["name", "lastModifiedDateTime"]  # Specify the fields to retrieve
    )

    if not results.get_count() is None:
        documents = [result for result in results]

        # Extract document IDs
        document_keys = [doc["id"] for doc in documents]

        # Delete documents
        batch = [{"@search.action": "delete", "id": key} for key in document_keys]
        search_client.upload_documents(documents=batch)
