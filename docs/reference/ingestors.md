# Ingestors

{% for ingestor in ingestors %}
## {{ ingestor.__name__ }}

`{{ ingestor.__module__ }}.{{ ingestor.__name__ }}`

{% if ingestor.MIME_TYPES %}
### File types

{% for type in ingestor.MIME_TYPES %}
- {{ type }}
{% endfor %}
{% endif %}

{% if ingestor.EXTENSIONS %}
### File extensions

{% for ext in ingestor.EXTENSIONS %}
- .{{ ext }}
{% endfor %}
{% endif %}

::: {{ ingestor.__module__ }}.{{ ingestor.__name__ }}
    options:
      heading_level: 3

{% endfor %}
