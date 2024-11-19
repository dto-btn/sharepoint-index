import logging
import os

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
from llama_index.core.schema import Document

__all__ = ["get_search_client", "get_vector_store", "update_index_with_document"]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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

METADATA_FIELDS = {
        'title': 'name',
        'url': 'webUrl',
        'id': 'id',
        'lastModifiedDateTime': 'lastModifiedDateTime'
    }

def get_search_client(index_name: str):
    """Returns the search client for an Azure Search Service"""
    return SearchClient(
        endpoint=service_endpoint,
        index_name=index_name.lower(),
        credential=search_key_credential
    )

def get_vector_store(index_name: str):
    """Retreive the vector store tied to an index or creates it if missing"""
    return AzureAISearchVectorStore(
        search_or_index_client=index_client,
        filterable_metadata_field_keys=METADATA_FIELDS,
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

def update_index_with_document(index_name: str, document: Document):
    """
    Create or re-use index passed in and returns vector store tied to it.
    """
    logger.info("Using search service endpoint: %s", service_endpoint)

    storage_context = StorageContext.from_defaults(vector_store=get_vector_store(index_name))

    index = VectorStoreIndex.from_documents([document], storage_context=storage_context)
    if index:
        return True
    return False
