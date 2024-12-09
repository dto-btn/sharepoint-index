import logging
import re
from datetime import datetime as dt

import requests

from .azure import get_search_client

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

__all__ = ["call_graph_api",
        "get_drives_info",
        "is_an_updated_document",
        "delete_document"]

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

    Returns a URL that is matching the passed in string
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
    if len(drives_info) > 1:
        return get_drives_info(new_url, token, drives_info[1:])
    return new_url

def is_an_updated_document(index_name: str, document_name: str, last_updated: str):
    """
    Search for documents in the specified index by their title and return the documents along with their timestamps.
    """
    search_client = get_search_client(index_name)

    search_query = f"title eq '{document_name}'"
    logger.info(search_query)

    results = search_client.search(
        search_text="*",  # Use wildcard to search for all documents
        filter=search_query,
        select=["title", "lastModifiedDateTime"],  # Specify the fields to retrieve
        include_total_count=True
    )

    if results.get_count() is None or results.get_count() == 0:
        logger.info(results.get_count())
        logger.info("No result(s) found, will need to update/insert document")
        return True

    for result in results:
        try:
            date_searched = dt.strptime(result['lastModifiedDateTime'], "%Y-%m-%dT%H:%M:%SZ")
            date_passed = dt.strptime(last_updated, "%Y-%m-%dT%H:%M:%SZ")
            logger.info("The file %s and the passed date %s and the search service returned date %s",
                        document_name,
                        date_passed, date_searched)
            if date_passed > date_searched:
                logger.info("Newer document detected")
                return True
        except ValueError:
            logger.warning("Unable to format date, will skip this entry")
    return False

def delete_document(index_name: str, document_name: str):
    """
    Delete documents that match this name from the index passed in parameter

    Returns an List of updated (deleted) documents
    """
    search_client = get_search_client(index_name)

    search_query = f"title eq '{escape_azure_search_special_chars(document_name)}'"
    logger.info(search_query)

    results = search_client.search(
        search_text="*",  # Use wildcard to search for all documents
        filter=search_query,
        select=["title", "lastModifiedDateTime"]  # Specify the fields to retrieve
    )

    if not results.get_count() is None:
        # Extract document IDs
        document_keys = [doc["id"] for doc in results]
        # Delete documents
        logger.info("Deleting those documents from the index: %s", document_keys)
        batch = [{"@search.action": "delete", "id": key} for key in document_keys]
        return search_client.upload_documents(documents=batch)
    return []

def escape_azure_search_special_chars(s):
    """
    Function to escape special characters for Azure Search

    Used AI to get this one.
    """
    special_chars = r'[\+\-\&\|\!\(\)\{\}\[\]\^\"\~\*\?\:\\/]'
    return re.sub(special_chars, r'\\\g<0>', s)
