{% for ingestor in ingestors %}
## {{ ingestor.__name__ }}

`{{ ingestor.__module__ }}.{{ ingestor.__name__ }}`

{% if ingestor.__doc__ %}
{{ ingestor.__doc__ }}
{% endif %}

### File types

{% for type in ingestor.MIME_TYPES %}
- {{ type }}
{% endfor %}

### File extensions

{% for ext in ingestor.EXTENSIONS %}
- .{{ ext }}
{% endfor %}

::: {{ ingestor.__module__ }}.{{ ingestor.__name__ }}

{% endfor %}
