# Ingest Pipeline

Ingesting files is a multi-step process. Depending on the file type, `ingest-file` may execute these different processing steps:

- Convert _Office_ documents into PDF for web display
- Extract text from documents and images (with [tesseract](https://github.com/tesseract-ocr/tesseract))
    - OCR results are cached for reuse
- Parse file contents and create a [FollowTheMoney](https://followthemoney.tech) object graph, e.g. for [`Email`](https://followthemoney.tech/explorer/schemata/Email/): Senders, recipients, attachments.
- At the end, dispatch extracted data to [ftm-analyze](https://docs.investigraph.dev/lib/ftm-analyze/) for pattern and entity extraction (NER)

!!! info
    This article describes the process of ingesting a Word document as an example. It is meant as a high-level overview of the system components and stages involved in the ingestion process. Depending on the file type and configuration options, the process might differ from what’s described here.

## Overview
The following graph shows an overview of all stages of the ingestion pipeline (for a Word document) as well as the system components handling each step. Continue reading below for a description of the individual stages.

!!! note
    The _analyze_ and _index_ steps of this graph are not part of `ingest-file`, but separate applications: [ftm-analyze](https://docs.investigraph.dev/lib/ftm-analyze/) and [OpenAleph](https://openaleph.org)

``` mermaid
graph LR
    subgraph client["input"]
    upload("Word file")
    end

    subgraph api["ingest-file"]
    archive("Archive file")
    dispatch-ingest("Dispatch ingest")
    end

    subgraph ingest-file-ingest["ingest-file (ingest)"]
    ingestor("Pick ingestor")
    metadata("Extract metadata")
    pdf("Convert to PDF")
    cache-pdf("Cache converted PDF")
    text("Extract text")
    fragments-ingest("Write fragments")
    dispatch-analyze("Dispatch analyze")
    end

    subgraph ingest-file-analyze["ftm-analyze (analyze)"]
    languages("Detect languages")
    ner("Run NER")
    patterns("Extract patterns")
    fragments-analyze("Write fragments")
    dispatch-index("Dispatch index")
    end

    subgraph worker["OpenAleph (index)"]
    index-worker("Index entities")
    stats("Update stats")
    end

    client-->api
    api-->ingest-file-ingest
    ingest-file-ingest-->ingest-file-analyze
    ingest-file-analyze-->worker

    archive-->dispatch-ingest

    ingestor-->metadata
    metadata-->pdf
    pdf-->cache-pdf
    cache-pdf-->text
    text-->fragments-ingest
    fragments-ingest-->dispatch-analyze

    languages-->ner
    ner-->patterns
    patterns-->fragments-analyze
    fragments-analyze-->dispatch-index

    index-worker-->stats
```

## User interface

Start the ingestion process for a file:

    ingestors ingest -d <my_dataset> -i ./path/to/Document.docx

!!! info
    There are many ways of getting a file into OpenAleph. End users looking to upload a small number of files may do so via the OpenAleph web UI. OpenAleph also provides a command-line client, [openaleph-client](https://openaleph.org/docs/user-guide/104/), that simplifies uploading files in bulk, and integrates with a scraping toolkit called [Memorious](https://docs.investigraph.dev/lib/memorious/). However, no matter which method of uploading files to OpenAleph you use, file uploads will always be handled by the `ingest-file` API and the rest of the pipeline will be the same.

## Archive file
In the first step, ingest-file stores the file using the configured storage backend. Storage backends are implemented in [servicelayer](https://github.com/alephdata/servicelayer). Supported backends include a simple backend using the host’s file system, AWS S3 (and other services with an S3-compatible API), and Google Cloud Storage.

Files are stored at a path that is inferred from the contents of the file by computing a SHA1 hash of the file’s contents. For example a file with the content hash `34d4e388b7994b3846504e89f54e10a6fd869eb8` would be stored at the path `34/d4/e3/34d4e388b7994b3846504e89f54e10a6fd869eb8`.

Storing files this way allows easy retrieval as long as the content hash is known, and ensures automatic deduplication if the same file is uploaded multiple times.

## Ingest
Ingest tasks are handled by ingest-file workers that run in separate containers. In order to ingest a file, the worker extracts the content hash and retrieves the file from the storage backend.

### Pick an ingestor
ingest-file supports many different file types (for example office documents, PDF, spreadsheets, …). To handle the specifics of each file type, ingest-file implements many different ingestors that handle the specific processing steps for each file type.

When an ingest-file worker picks up a new file to ingest, it tries to find the most specific ingestor based on the file’s mime type or file extension. In case of the Word document, ingest-file picks the [OfficeOpenXMLIngestor](https://github.com/openaleph/ingest-file/blob/main/ingestors/documents/ooxml.py) which is suitable for parsing documents in [Office Open XML](https://en.wikipedia.org/wiki/Office_Open_XML) formats used by recent versions of Microsoft Word and PowerPoint.

Depending on the file type, other investors may be used to ingest the file and the processing steps might vary more or less. For example, when uploading a text document created with LibreOffice Writer, a different investor will be used, but many of the subsequent processing steps will be the same. However, when uploading an email mailbox, the processing steps will differ significantly.

### Extract document metadata
First, the ingestor extracts metadata from the document, for example the document title, author, and creation/modification timestamps.

### Convert to PDF
For further processing and previewing in the OpenAleph web UI, ingest-file converts many common Office-like file types to a PDF file. It uses a headless LibreOffice subprocess to convert the Word file (previously retrieved from the storage backend) to a PDF file

The resulting PDF file is stored using the configured storage backend (in the same way the source Word file was stored, i.e. a SHA1 hash is computed and used to derive the path the PDF file is stored at).

ingest-file sets the [`pdfHash`](https://followthemoney.tech/explorer/schemata/Pages/#pdfHash) property on the FtM entity representing the uploaded file, so the converted PDF file is available to subsequent processing steps.

### Cache PDF conversion results
ingest-file also caches the result of the PDF conversion. When a source file with the same content hash is uploaded a second time, it will reuse the converted PDF document instead of converting it again.

### Extract text
Using the generated PDF file, ingest-file then uses [PyMuPDF](https://github.com/pymupdf/PyMuPDF) to extract text contents from the PDF file. Ingest-file will also run optical character recognition (OCR) to extract text contents from images embedded in the PDF file. That means that ingest-file is able to extract text from scanned documents.

!!! info
    Under the hood, ingest-file uses [followthemoney-store](https://github.com/alephdata/followthemoney-store) to store entity data. [followthemoney-store](https://github.com/alephdata/followthemoney-store) stores entity data as "fragments". Every fragment stores a subset of the properties. [Read more about fragments](https://followthemoney.tech/docs/fragments/)

For every page in the Word document, ingest-file emits an entity fragment for a main `Pages` entity that contains the extracted text. Thus, once these fragments are merged into a single `Pages` entity, there exists one `Pages` entity that contains the extracted text for the entire document.

In addition, for every page, OpenAleph emits a separate `Page` entity fragment that contains the extracted text of a single page, metadata (e.g. the page number), and a reference to the main `Pages` entity.

This way, users can search for documents that contain a search query on any of the pages, or for individual pages within in a specific document that contain the search query.

### Write fragments
Any entities that have been emitted in the process so far (i.e. one `Pages` entity and multiple `Page` entities) are now written to FtM store, the Postgres database that acts as the “source of truth” for all entity data.

At this point, FtM store will contain multiple entity fragments related to the uploaded file:

<table>
  <tr>
    <th>id</th>
    <th>origin</th>
    <th>fragment</th>
    <th>data</th>
  </tr>
  <tr>
    <td>97e1f...</td>
    <td>ingest</td>
    <td>default</td>
    <td>
```json
// File metadata and hashes of source and PDF files
{
  "schema": "Pages",
  "properties": {
    "fileName": ["my-file.docx"],
    "contentHash": ["128e0..."],
    "pdfHash": ["5355c..."],
    // ...
  }
}
```
    </td>
  </tr>
  <tr>
    <td>97e1f...</td>
    <td>ingest</td>
    <td>eae30...</td>
    <td>
```json
{
  "schema": "Pages",
  "properties": {
    "indexText": ["Text content page 1..."]
  }
}
```
    </td>
  </tr>
  <tr>
    <td>97e1f...</td>
    <td>ingest</td>
    <td>544d4...</td>
    <td>
```json
{
  "schema": "Pages",
  "properties": {
    "indexText": ["Text content page 2..."]
  }
}
```
    </td>
  </tr>
  <tr>
    <td>c00b3...</td>
    <td>ingest</td>
    <td>default</td>
    <td>
```json
// `Page` entity for the first page
{
  "schema": "Page",
  "properties": {
    "index": ["1"],
    "bodyText": ["Text content page 1..."],
    "document": ["97e1f..."], // ID of the `Pages` entity
    // ...
  }
}
```
    </td>
  </tr>
  <tr>
    <td>81424...</td>
    <td>ingest</td>
    <td>default</td>
    <td>
```json
// `Page` entity for the second page
{
  "schema": "Page",
  "properties": {
    "index": ["2"],
    "bodyText": ["Text content page 2..."],
    "document": ["97e1f..."], // ID of the `Pages` entity
    // ...
  }
}
```
    </td>
  </tr>
</table>

### Dispatch analyze task

Finally, the ingestor dispatches an `analyze` task. This pushes a task object to the relevant task queue. The task object includes the IDs of all entities written in the previous step.

The `analyze` task is handled by a separate package, `ftm-analyze`. It reads the task object from the worker queue and executes its own pipeline. [Refer to its documentation to learn more.](https://docs.investigraph.dev/lib/ftm-analyze/pipeline)

After analysis, the data is ready to index into OpenAleph or use by other systems.

---

> Thanks to [Till Prochaska](https://github.com/tillprochaska) who initially wrote up the pipeline for the original Aleph Documentation
