from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Page-number pagination that lets clients widen the page via ?page_size=.

    The bulk-tagging use case wants every image in one request, so allow a
    generous ceiling while keeping a sane default.
    """

    page_size_query_param = "page_size"
    max_page_size = 1000
