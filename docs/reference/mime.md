---
hide:
  – toc
---

# Supported file types

| Mimetype | Label | Extension |
| -------- | ----- | --------- |
{% for m in mimetypes %}| `{{ m.name }}` | {{ m.label }} | {{ m.ext | default('') }} |
{% endfor %}
