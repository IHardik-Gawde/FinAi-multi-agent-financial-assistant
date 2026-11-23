
import { useState, useEffect, useRef } from 'react'
import { Room, RoomEvent, Track, createLocalAudioTrack } from 'livekit-client'
import './App.css'

// FINANCIAL RECORDS COMPONENT
function FinancialRecords({
  records,
  recordType,
  setRecordType,
  showRecordForm,
  setShowRecordForm,
  newRecord,
  setNewRecord,
  onSaveRecord,
  onUpdateRecord,
  onDeleteRecord,
  recordLoading,
  recordError,
}) {
  const [editingId, setEditingId] = useState(null)

  const income = records
    .filter((record) => record.type === 'Income')
    .reduce((sum, record) => sum + Number(record.amount), 0)

  const expenses = records
    .filter((record) => record.type === 'Expense')
    .reduce((sum, record) => sum + Number(record.amount), 0)

  const filteredRecords =
    recordType === 'All'
      ? records
      : records.filter((record) => record.type === recordType)

  const resetForm = () => {
    setNewRecord({
      title: '',
      type: 'Income',
      amount: '',
      date: new Date().toISOString().split('T')[0],
    })
    setEditingId(null)
    setShowRecordForm(false)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!newRecord.title.trim() || !newRecord.amount || Number(newRecord.amount) <= 0) return

    const payload = {
      title: newRecord.title.trim(),
      type: newRecord.type,
      amount: newRecord.amount,
      date: newRecord.date,
    }

    const succeeded = editingId
      ? await onUpdateRecord(editingId, payload)
      : await onSaveRecord(payload)

    if (succeeded) resetForm()
  }

  const handleEdit = (record) => {
    setNewRecord({
      title: record.title,
      type: record.type,
      amount: String(record.amount),
      date: record.date,
    })
    setEditingId(record.id)
    setShowRecordForm(true)
  }

  return (
    <section className="records-screen">
      <div className="records-heading">
        <div>
          <span className="eyebrow">FINANCIAL MANAGEMENT</span>
          <h1>Financial Records</h1>
          <p>Manage and review your income and expenses.</p>
        </div>
        <button
          className="add-record-button"
          onClick={() => {
            if (showRecordForm) {
              resetForm()
            } else {
              setEditingId(null)
              setNewRecord({
                title: '',
                type: 'Income',
                amount: '',
                date: new Date().toISOString().split('T')[0],
              })
              setShowRecordForm(true)
            }
          }}
        >
          + Add Record
        </button>
      </div>

      <div className="records-stats">
        <div className="stat-card">
          <div className="stat-card-top"><span>Total Income</span><div className="stat-icon">↗</div></div>
          <h2>₹{income.toLocaleString('en-IN')}</h2>
          <p>Recorded income</p>
        </div>
        <div className="stat-card">
          <div className="stat-card-top"><span>Total Expenses</span><div className="stat-icon">↘</div></div>
          <h2>₹{expenses.toLocaleString('en-IN')}</h2>
          <p>Recorded expenses</p>
        </div>
        <div className="stat-card">
          <div className="stat-card-top"><span>Net Balance</span><div className="stat-icon">◈</div></div>
          <h2>₹{(income - expenses).toLocaleString('en-IN')}</h2>
          <p>Income minus expenses</p>
        </div>
      </div>

      {showRecordForm && (
        <form className="record-form" onSubmit={handleSubmit}>
          <div className="record-form-heading">
            <div>
              <span className="eyebrow">{editingId ? 'UPDATE ENTRY' : 'NEW ENTRY'}</span>
              <h3>{editingId ? 'Edit Financial Record' : 'Add Financial Record'}</h3>
            </div>
          </div>
          <div className="record-form-grid">
            <input
              type="text"
              placeholder="Record description"
              value={newRecord.title}
              onChange={(event) => setNewRecord({ ...newRecord, title: event.target.value })}
              required
            />
            <select
              value={newRecord.type}
              onChange={(event) => setNewRecord({ ...newRecord, type: event.target.value })}
            >
              <option value="Income">Income</option>
              <option value="Expense">Expense</option>
            </select>
            <input
              type="number"
              min="0.01"
              step="0.01"
              placeholder="Amount (₹)"
              value={newRecord.amount}
              onChange={(event) => setNewRecord({ ...newRecord, amount: event.target.value })}
              required
            />
            <input
              type="date"
              value={newRecord.date}
              onChange={(event) => setNewRecord({ ...newRecord, date: event.target.value })}
              required
            />
          </div>
          <div className="record-form-actions">
            <button type="button" onClick={resetForm}>Cancel</button>
            <button type="submit">{editingId ? 'Update Record' : 'Save Record'}</button>
          </div>
        </form>
      )}

      {recordError && <p className="notice">{recordError}</p>}

      <div className="records-panel">
        <div className="records-toolbar">
          <div>
            <span className="eyebrow">TRANSACTION HISTORY</span>
            <h3>All Records</h3>
          </div>
          <select value={recordType} onChange={(event) => setRecordType(event.target.value)}>
            <option value="All">All Records</option>
            <option value="Income">Income</option>
            <option value="Expense">Expenses</option>
          </select>
        </div>

        {recordLoading ? (
          <div className="records-empty"><strong>Loading financial records...</strong></div>
        ) : filteredRecords.length === 0 ? (
          <div className="records-empty">
            <div className="empty-icon">▤</div>
            <strong>No financial records found</strong>
            <p>Add a record to start building your transaction history.</p>
          </div>
        ) : (
          <div className="records-table-wrapper">
            <table className="records-table">
              <thead>
                <tr><th>Description</th><th>Type</th><th>Date</th><th>Amount</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {filteredRecords.map((record) => (
                  <tr key={record.id}>
                    <td>{record.title}</td>
                    <td><span className={`record-type ${record.type.toLowerCase()}`}>{record.type}</span></td>
                    <td>{record.date}</td>
                    <td>{record.type === 'Income' ? '+' : '-'}₹{Number(record.amount).toLocaleString('en-IN')}</td>
                    <td>
                      <button type="button" onClick={() => handleEdit(record)}>Edit</button>
                      {' '}
                      <button type="button" onClick={() => onDeleteRecord(record.id)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="records-footer">
        Financial records are saved in your backend database.
      </div>
    </section>
  )
}


// DOCUMENT MANAGEMENT PAGE
function DocumentsPage() {
  const API = 'http://127.0.0.1:8000'

  const [searchTerm, setSearchTerm] = useState('')
  const [category, setCategory] = useState('All')
  const [loading, setLoading] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [ragQuery, setRagQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchResults, setSearchResults] = useState([])
  const [documents, setDocuments] = useState([])
  const [selectedDocuments, setSelectedDocuments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [queuedFiles, setQueuedFiles] = useState([])
  const [pendingUploadId, setPendingUploadId] = useState(null)
  const [extractedText, setExtractedText] = useState('')
  const [extractedFields, setExtractedFields] = useState(null)
  const [reviewedFields, setReviewedFields] = useState({})
  const [processing, setProcessing] = useState(false)
  const [savingRecord, setSavingRecord] = useState(false)
  const [savedRecords, setSavedRecords] = useState([])
  const [editingSavedRecord, setEditingSavedRecord] = useState(null)
  const [savedFieldsText, setSavedFieldsText] = useState('')
  const [updatingSavedRecord, setUpdatingSavedRecord] = useState(false)


  const loadDocuments = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await fetch(`${API}/documents`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Unable to load documents')

      setDocuments((data.documents || []).map((doc) => {
        const extension = (doc.extension || '').toLowerCase()
        const imageExtensions = ['.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp']
        return {
          id: doc.filename,
          name: doc.filename,
          size: doc.size || 0,
          category: imageExtensions.includes(extension)
            ? 'Image'
            : extension === '.pdf' ? 'PDF' : 'Other',
          addedAt: doc.modified
            ? new Date(doc.modified * 1000).toLocaleDateString('en-IN')
            : '—',
        }
      }))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const loadSavedRecords = async () => {
    try {
      const response = await fetch(`${API}/documents/records`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Unable to load saved records')
      setSavedRecords(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    loadDocuments()
    loadSavedRecords()
  }, [])

  const savedRecordEditorRef = useRef(null)

  const startEditingSavedRecord = (record) => {
    if (!record) {
      setError('No saved extracted data was found for this document. Refresh the document list and try again.')
      return
    }
    setEditingSavedRecord(record)
    setSavedFieldsText(JSON.stringify(record.fields || {}, null, 2))
    setError('')
    setMessage('')
  }

  useEffect(() => {
    if (editingSavedRecord) {
      savedRecordEditorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [editingSavedRecord])

  const saveExistingRecord = async () => {
    if (!editingSavedRecord) return
    let fields
    try {
      fields = JSON.parse(savedFieldsText)
      if (!fields || Array.isArray(fields) || typeof fields !== 'object') {
        throw new Error('The fields must be a JSON object.')
      }
    } catch (err) {
      setError(`Invalid field data: ${err.message}`)
      return
    }
    setUpdatingSavedRecord(true)
    setError('')
    setMessage('')
    try {
      const response = await fetch(`${API}/documents/records/${editingSavedRecord.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields, confidence: editingSavedRecord.confidence || 'low' }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Unable to update saved record')
      setMessage('Saved extracted data updated. The original PDF was not changed.')
      setEditingSavedRecord(null)
      setSavedFieldsText('')
      await loadSavedRecords()
    } catch (err) {
      setError(err.message)
    } finally {
      setUpdatingSavedRecord(false)
    }
  }

  const discardPendingUpload = async (uploadId = pendingUploadId) => {
    if (!uploadId) return
    try {
      await fetch(`${API}/documents/pending/${encodeURIComponent(uploadId)}`, {
        method: 'DELETE',
      })
    } catch (discardError) {
      console.warn('Unable to discard temporary upload:', discardError)
    }
  }

  const resetDocumentReview = async () => {
    await discardPendingUpload()
    setPendingUploadId(null)
    setSelectedFile(null)
    setQueuedFiles([])
    setExtractedText('')
    setExtractedFields(null)
    setReviewedFields({})
    setMessage('Review cleared. The unconfirmed upload and remaining batch were discarded.')
    setError('')
  }

  const processDocument = async (file) => {
    if (!file) return

    await discardPendingUpload()
    setPendingUploadId(null)
    setSelectedFile(file)
    setExtractedText('')
    setExtractedFields(null)
    setReviewedFields({})
    setMessage('')
    setError('')
    setProcessing(true)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const response = await fetch(`${API}/documents/process`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Document processing failed')

      const extraction = data.extracted_fields || {}
      const fields = extraction.fields || {}
      setExtractedText(data.extracted_text || '')
      setExtractedFields(extraction)
      setReviewedFields(Object.fromEntries(
        Object.entries(fields).map(([key, value]) => [
          key,
          value !== null && typeof value === 'object'
            ? JSON.stringify(value, null, 2)
            : value == null ? '' : String(value),
        ])
      ))
      setPendingUploadId(data.upload_id)
      setMessage(data.message || 'Document processed for review. Nothing has been saved or indexed yet.')
    } catch (err) {
      setError(err.message)
    } finally {
      setProcessing(false)
    }
  }

  const saveExtractedRecord = async (event) => {
    event.preventDefault()
    if (!selectedFile || !pendingUploadId || !extractedFields || extractedFields.document_type === 'unknown') return

    let fieldsToSave = {}
    try {
      for (const [key, value] of Object.entries(reviewedFields)) {
        const originalValue = extractedFields.fields?.[key]
        if (originalValue !== null && typeof originalValue === 'object') {
          fieldsToSave[key] = value.trim() ? JSON.parse(value) : (Array.isArray(originalValue) ? [] : {})
        } else if (value === '') {
          fieldsToSave[key] = null
        } else if (typeof originalValue === 'number') {
          const numericValue = Number(value)
          if (!Number.isFinite(numericValue)) throw new Error(`${key.replaceAll('_', ' ')} must be a valid number.`)
          fieldsToSave[key] = numericValue
        } else {
          fieldsToSave[key] = value
        }
      }
    } catch (parseError) {
      setError(`Please correct the structured field format: ${parseError.message}`)
      return
    }

    setSavingRecord(true)
    setError('')
    try {
      const response = await fetch(`${API}/documents/records`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: pendingUploadId,
          document_type: extractedFields.document_type,
          fields: fieldsToSave,
          confidence: extractedFields.confidence || 'low',
        }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Unable to save reviewed document')
      setPendingUploadId(null)
      setExtractedText('')
      setExtractedFields(null)
      setReviewedFields({})
      await loadDocuments()
      await loadSavedRecords()

      const nextFile = queuedFiles[0]
      if (nextFile) {
        setQueuedFiles((current) => current.slice(1))
        setMessage(`${selectedFile.name} saved. Processing the next file in the batch...`)
        await processDocument(nextFile)
      } else {
        setSelectedFile(null)
        setQueuedFiles([])
        setMessage(data.message || 'Document confirmed and saved successfully.')
      }
    } catch (saveError) {
      setError(saveError.message)
    } finally {
      setSavingRecord(false)
    }
  }

  const removeDocument = async (filename) => {
    if (!window.confirm(`Delete ${filename}?`)) return
    setError('')
    setMessage('')
    try {
      const response = await fetch(
        `${API}/documents/${encodeURIComponent(filename)}`,
        { method: 'DELETE' }
      )
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Unable to delete document')
      setMessage('Document deleted successfully.')
      setSelectedDocuments((current) => current.filter((name) => name !== filename))
      setSearchResults([])
      await loadDocuments()
      await loadSavedRecords()
    } catch (err) {
      setError(err.message)
    }
  }

  const toggleDocumentSelection = (filename) => {
    setSelectedDocuments((current) =>
      current.includes(filename)
        ? current.filter((name) => name !== filename)
        : [...current, filename]
    )
  }

  const toggleAllVisibleDocuments = (checked) => {
    setSelectedDocuments((current) => {
      if (checked) {
        return [...new Set([...current, ...visibleDocuments.map((doc) => doc.name)])]
      }
      const visibleNames = new Set(visibleDocuments.map((doc) => doc.name))
      return current.filter((name) => !visibleNames.has(name))
    })
  }

  const removeSelectedDocuments = async () => {
    const filenames = selectedDocuments.filter((name) =>
      documents.some((doc) => doc.name === name)
    )
    if (!filenames.length) return
    if (!window.confirm(`Permanently delete ${filenames.length} selected document(s)? This also removes their database records and indexed content.`)) return

    setError('')
    setMessage('')
    let deleted = []
    let failed = []

    for (const filename of filenames) {
      try {
        const response = await fetch(
          `${API}/documents/${encodeURIComponent(filename)}`,
          { method: 'DELETE' }
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || 'Unable to delete document')
        deleted.push(filename)
      } catch (deleteError) {
        failed.push(`${filename}: ${deleteError.message}`)
      }
    }

    setSelectedDocuments((current) => current.filter((name) => !deleted.includes(name)))
    setSearchResults([])
    await loadDocuments()
    await loadSavedRecords()

    if (failed.length) {
      setError(`Deleted ${deleted.length} document(s). Failed to delete: ${failed.join(' | ')}`)
    } else {
      setMessage(`Successfully deleted ${deleted.length} selected document(s).`)
    }
  }

  const handleIndex = async () => {
    setIndexing(true)
    setError('')
    setMessage('')
    try {
      const response = await fetch(`${API}/documents/index`, { method: 'POST' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Indexing failed')
      setMessage(
        `Indexing complete. ${data.total_documents ?? documents.length} documents processed; ${data.index_size ?? '—'} chunks in FAISS.`
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setIndexing(false)
    }
  }

  const handleSearch = async (event) => {
    event.preventDefault()
    if (!ragQuery.trim()) return
    setSearching(true)
    setError('')
    setMessage('')
    setSearchResults([])
    try {
      const response = await fetch(`${API}/documents/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: ragQuery.trim(), top_k: 3 }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Document search failed')
      setSearchResults(data.results || [])
      setMessage(data.results?.length
        ? `${data.results.length} relevant chunk(s) retrieved.`
        : 'No matching document content found.')
    } catch (err) {
      setError(err.message)
    } finally {
      setSearching(false)
    }
  }

  const visibleDocuments = documents.filter((doc) => {
    const matchesSearch = doc.name.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesCategory = category === 'All' || doc.category === category
    return matchesSearch && matchesCategory
  })

  const savedRecordByFilename = new Map(
    savedRecords.map((record) => [record.filename, record])
  )

  const formatSize = (bytes) => {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <section className="workspace-page documents-screen">
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">KNOWLEDGE LIBRARY</span>
          <h1>Document Intelligence</h1>
          <p>Upload once to extract, review, store and search financial documents.</p>
        </div>
        <label className="primary-action upload-document-button">
          {processing
            ? 'Processing batch...'
            : queuedFiles.length
              ? `+ ${queuedFiles.length} file(s) remaining`
              : '+ Upload document(s)'}
          <input
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"
            disabled={processing || Boolean(pendingUploadId)}
            onChange={(event) => {
              const files = Array.from(event.target.files || [])
              if (files.length) {
                setQueuedFiles(files.slice(1))
                processDocument(files[0])
              }
              event.target.value = ''
            }}
          />
        </label>
      </div>


      {(processing || selectedFile || extractedText) && (
        <div className="ocr-layout document-processing-layout">
          <div className="workspace-panel ocr-upload-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">DOCUMENT PROCESSING</span>
                <h3>{selectedFile?.name || 'Selected document'}</h3>
              </div>
              <span className="panel-tag">{processing ? 'Processing' : pendingUploadId ? 'Awaiting confirmation' : extractedFields?.record_saved ? 'Saved & indexed' : 'Review unavailable'}</span>
            </div>
            <p className="ocr-process-note">
              {processing
                ? 'Extracting document text and suggesting financial fields in temporary storage...'
                : 'The document is being processed in temporary storage. It will enter your library and FAISS only after you confirm.'}
              {queuedFiles.length > 0 && ` ${queuedFiles.length} more file(s) will be processed after this document is confirmed.`}
            </p>
            {extractedText && (
              <label className="workspace-form">
                Extracted document text
                <textarea value={extractedText} readOnly rows={12} aria-label="Extracted document text" />
              </label>
            )}
            {!processing && selectedFile && (
              <div className="record-form-actions">
                <button type="button" className="secondary-action" onClick={resetDocumentReview}>Clear review & batch</button>
                {error && queuedFiles.length > 0 && (
                  <button
                    type="button"
                    className="secondary-action"
                    onClick={async () => {
                      await discardPendingUpload()
                      setPendingUploadId(null)
                      const nextFile = queuedFiles[0]
                      setQueuedFiles((current) => current.slice(1))
                      if (nextFile) {
                        await processDocument(nextFile)
                      } else {
                        setSelectedFile(null)
                        setExtractedText('')
                        setExtractedFields(null)
                        setReviewedFields({})
                      }
                    }}
                  >
                    Skip file & process next
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="workspace-panel ocr-review-panel">
            <div className="review-panel-heading">
              <div>
                <span className="eyebrow">DOCUMENT ANALYSIS</span>
                <h3>Review extracted details</h3>
                <p>Verify the information below before saving it to your finance workspace.</p>
              </div>
              <span className={`review-state ${processing ? 'is-processing' : extractedFields ? `confidence-${(extractedFields.confidence || 'low').toLowerCase()}` : ''}`}>
                <span className="review-state-dot" />
                {processing ? 'Processing' : extractedFields ? `${(extractedFields.confidence || 'low').toUpperCase()} CONFIDENCE` : 'AWAITING EXTRACTION'}
              </span>
            </div>

            {extractedFields && (
              <>
                <div className="document-review-summary">
                  <div className="document-type-mark">
                    <span className="document-type-icon">▤</span>
                    <div>
                      <span className="review-meta-label">DETECTED DOCUMENT TYPE</span>
                      <strong>{(extractedFields.document_type || 'unknown').replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())}</strong>
                    </div>
                  </div>
                  <div className="review-summary-divider" />
                  <div className="review-summary-stat">
                    <span className="review-meta-label">FIELDS EXTRACTED</span>
                    <strong>{Object.keys(extractedFields.fields || {}).filter((key) => extractedFields.fields[key] !== null && extractedFields.fields[key] !== '' && !(Array.isArray(extractedFields.fields[key]) && extractedFields.fields[key].length === 0)).length}</strong>
                  </div>
                  <div className="review-summary-stat">
                    <span className="review-meta-label">REQUIRES ATTENTION</span>
                    <strong>{extractedFields.missing_fields?.length || 0}</strong>
                  </div>
                </div>
                <p className="review-guidance">
                  Review the suggested values and make corrections where needed. Fields that could not be confidently extracted can be completed manually.
                </p>
                {extractedFields.missing_fields?.length > 0 && (
                  <p className="review-alert">
                    <strong>Missing required fields</strong>
                    <span>{extractedFields.missing_fields.map((field) => field.replaceAll('_', ' ')).join(', ')}</span>
                  </p>
                )}
                {extractedFields.validation_warnings?.map((warning, index) => (
                  <p className="notice" key={`${warning}-${index}`}>{warning}</p>
                ))}
                <form className="workspace-form" onSubmit={saveExtractedRecord}>
                  <div className="form-two-col">
                    {Object.entries(reviewedFields).map(([key, value]) => {
                      const originalValue = extractedFields.fields?.[key]
                      const isStructured = originalValue !== null && typeof originalValue === 'object'
                      const isLineItems = key === 'line_items' && Array.isArray(originalValue)
                      const isNumber = typeof originalValue === 'number'
                      const isDate = key.endsWith('_date') || key.startsWith('statement_period_')
                      const label = key.replaceAll('_', ' ').replace(/\\b\\w/g, (char) => char.toUpperCase())

                      if (isLineItems) {
                        let lineItems = []
                        try {
                          const parsed = JSON.parse(value || '[]')
                          lineItems = Array.isArray(parsed) ? parsed : []
                        } catch {
                          lineItems = []
                        }

                        const updateLineItem = (index, field, nextValue) => {
                          const updated = lineItems.map((item, itemIndex) =>
                            itemIndex === index
                              ? {
                                ...item,
                                [field]: field === 'description'
                                  ? nextValue
                                  : nextValue === '' ? '' : Number(nextValue),
                              }
                              : item
                          )
                          setReviewedFields((current) => ({
                            ...current,
                            [key]: JSON.stringify(updated, null, 2),
                          }))
                        }

                        const addLineItem = () => {
                          setReviewedFields((current) => {
                            let currentItems = []
                            try {
                              const parsed = JSON.parse(current[key] || '[]')
                              currentItems = Array.isArray(parsed) ? parsed : []
                            } catch {
                              currentItems = []
                            }
                            return {
                              ...current,
                              [key]: JSON.stringify([
                                ...currentItems,
                                { description: '', quantity: 1, unit_price: 0, amount: 0 },
                              ], null, 2),
                            }
                          })
                        }

                        const removeLineItem = (index) => {
                          const updated = lineItems.filter((_, itemIndex) => itemIndex !== index)
                          setReviewedFields((current) => ({
                            ...current,
                            [key]: JSON.stringify(updated, null, 2),
                          }))
                        }

                        return (
                          <div className="line-items-review" style={{ gridColumn: '1 / -1' }} key={key}>
                            <div className="line-items-review-heading">
                              <div>
                                <strong>{label}</strong>
                                <span>{lineItems.length} item{lineItems.length === 1 ? '' : 's'} extracted · Edit values before saving</span>
                              </div>
                              <button type="button" className="secondary-action" onClick={addLineItem}>
                                + Add item
                              </button>
                            </div>
                            <div className="records-table-wrapper">
                              <table className="records-table line-items-table">
                                <thead>
                                  <tr>
                                    <th>Description</th>
                                    <th>Qty</th>
                                    <th>Unit price</th>
                                    <th>Amount</th>
                                    <th>Action</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {lineItems.length === 0 ? (
                                    <tr>
                                      <td colSpan="5">No line items extracted. Add them manually if needed.</td>
                                    </tr>
                                  ) : lineItems.map((item, index) => (
                                    <tr key={`${index}-${item.description || 'item'}`}>
                                      <td>
                                        <input
                                          type="text"
                                          aria-label={`Item ${index + 1} description`}
                                          value={item.description ?? ''}
                                          onChange={(event) => updateLineItem(index, 'description', event.target.value)}
                                        />
                                      </td>
                                      <td>
                                        <input
                                          type="number"
                                          min="0"
                                          step="any"
                                          aria-label={`Item ${index + 1} quantity`}
                                          value={item.quantity ?? ''}
                                          onChange={(event) => updateLineItem(index, 'quantity', event.target.value)}
                                        />
                                      </td>
                                      <td>
                                        <input
                                          type="number"
                                          min="0"
                                          step="0.01"
                                          aria-label={`Item ${index + 1} unit price`}
                                          value={item.unit_price ?? ''}
                                          onChange={(event) => updateLineItem(index, 'unit_price', event.target.value)}
                                        />
                                      </td>
                                      <td>
                                        <input
                                          type="number"
                                          min="0"
                                          step="0.01"
                                          aria-label={`Item ${index + 1} amount`}
                                          value={item.amount ?? ''}
                                          onChange={(event) => updateLineItem(index, 'amount', event.target.value)}
                                        />
                                      </td>
                                      <td>
                                        <button type="button" className="remove-document" onClick={() => removeLineItem(index)}>
                                          Remove
                                        </button>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )
                      }

                      return (
                        <label style={isStructured ? { gridColumn: '1 / -1' } : undefined} key={key}>
                          {label}
                          {isStructured ? (
                            <textarea
                              rows={Math.min(8, Math.max(3, String(value).split('\\n').length))}
                              value={value}
                              onChange={(event) => setReviewedFields((current) => ({ ...current, [key]: event.target.value }))}
                              spellCheck={false}
                            />
                          ) : (
                            <input
                              type={isNumber ? 'number' : isDate ? 'date' : 'text'}
                              step={isNumber ? 'any' : undefined}
                              value={value}
                              placeholder={`Enter ${label.toLowerCase()}`}
                              onChange={(event) => setReviewedFields((current) => ({ ...current, [key]: event.target.value }))}
                            />
                          )}
                        </label>
                      )
                    })}
                  </div>
                  <div className="ocr-confirm-row">
                    <p>Nothing is saved to the structured database until you confirm. Line items can be edited in the table above. Other complex fields, such as statement transactions, remain in structured JSON format.</p>
                    <button
                      className="primary-action"
                      type="submit"
                      disabled={processing || savingRecord || !extractedText || !pendingUploadId || extractedFields.document_type === 'unknown' || extractedFields.record_saved}
                    >
                      {savingRecord ? 'Saving...' : extractedFields.record_saved ? 'Record saved' : 'Confirm & save document record'}
                    </button>
                  </div>
                </form>
              </>
            )}
          </div>
        </div>
      )}

      <div className="document-summary">
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Total documents</span>
          <strong>{documents.length}</strong>
          <span className="summary-footnote">Backend storage</span>
        </div>
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">PDF files</span>
          <strong>{documents.filter((doc) => doc.category === 'PDF').length}</strong>
          <span className="summary-footnote">Reports and statements</span>
        </div>
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Images</span>
          <strong>{documents.filter((doc) => doc.category === 'Image').length}</strong>
          <span className="summary-footnote">Receipts and scans</span>
        </div>
      </div>

      {(processing || indexing) && (
        <p className="inline-message">
          {processing ? 'Processing and indexing document...' : 'Indexing documents into FAISS...'}
        </p>
      )}
      {message && <p className="inline-message">{message}</p>}
      {error && <p className="notice">{error}</p>}

      <div className="workspace-panel document-library">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">RETRIEVAL AUGMENTED GENERATION</span>
            <h3>Search your documents</h3>
          </div>
          <span className="panel-tag">FAISS Search</span>
        </div>
        <form className="document-filters" onSubmit={handleSearch}>
          <input
            value={ragQuery}
            onChange={(event) => {
              setRagQuery(event.target.value)
              setSearchResults([])
            }}
            placeholder="Ask something about your uploaded financial documents..."
          />
          <button
            className="primary-action"
            type="submit"
            disabled={searching || !ragQuery.trim()}
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
        </form>

        {searchResults.length > 0 && (
          <div className="document-list">
            {searchResults.map((result, index) => (
              <div className="document-row" key={`${result.source}-${index}`}>
                <div className="document-file-icon">RAG</div>
                <div className="document-file-info">
                  <strong>{result.source}</strong>
                  <span>Relevance score: {Number(result.score).toFixed(4)}</span>
                  <p>{result.text}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="workspace-panel document-library">
        <div className="document-toolbar">
          <div>
            <span className="eyebrow">YOUR FILES</span>
            <h3>Document library</h3>
          </div>
          <div className="document-filters">
            <input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Search documents..."
            />
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option>All</option>
              <option>PDF</option>
              <option>Image</option>
              <option>Other</option>
            </select>
          </div>
        </div>

        <div className="record-form-actions">
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="checkbox"
              checked={visibleDocuments.length > 0 && visibleDocuments.every((doc) => selectedDocuments.includes(doc.name))}
              onChange={(event) => toggleAllVisibleDocuments(event.target.checked)}
              disabled={visibleDocuments.length === 0 || loading || processing}
            />
            Select all visible
          </label>
          <button
            type="button"
            className="remove-document"
            onClick={removeSelectedDocuments}
            disabled={selectedDocuments.length === 0 || loading || processing}
          >
            Delete selected ({selectedDocuments.length})
          </button>
          <button type="button" onClick={loadDocuments} disabled={loading}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
          <button
            type="button"
            onClick={handleIndex}
            disabled={indexing || processing || documents.length === 0}
          >
            {indexing ? 'Indexing...' : 'Index documents'}
          </button>
        </div>

        {loading ? (
          <div className="workspace-empty">Loading documents...</div>
        ) : visibleDocuments.length === 0 ? (
          <div className="workspace-empty">
            <div className="empty-icon">▱</div>
            <strong>{documents.length ? 'No matching documents' : 'Your library is empty'}</strong>
            <p>
              {documents.length
                ? 'Try another search or file category.'
                : 'Upload reports, invoices, and supporting files to start your library.'}
            </p>

          </div>
        ) : (
          <div className="document-list">
            {visibleDocuments.map((doc) => (
              <div className="document-row" key={doc.id}>
                <input
                  type="checkbox"
                  aria-label={`Select ${doc.name}`}
                  checked={selectedDocuments.includes(doc.name)}
                  onChange={() => toggleDocumentSelection(doc.name)}
                />
                <div className="document-file-icon">
                  {doc.category === 'PDF' ? 'PDF' : doc.category === 'Image' ? 'IMG' : 'FILE'}
                </div>
                <div className="document-file-info">
                  <strong>{doc.name}</strong>
                  <span>{doc.category} · {formatSize(doc.size)} · Added {doc.addedAt}</span>
                </div>
                <div className="document-row-actions">
                  <a
                    className="document-action-link"
                    href={`${API}/documents/file/${encodeURIComponent(doc.name)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View original
                  </a>
                  {savedRecordByFilename.has(doc.name) && (
                    <button
                      type="button"
                      className="document-action-button"
                      onClick={() => startEditingSavedRecord(savedRecordByFilename.get(doc.name))}
                    >
                      Edit data
                    </button>
                  )}
                  <button
                    className="remove-document"
                    type="button"
                    onClick={() => removeDocument(doc.name)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editingSavedRecord && (
        <div className="workspace-panel saved-record-editor" ref={savedRecordEditorRef}>
          <div className="document-toolbar">
            <div>
              <span className="eyebrow">POST-SAVE CORRECTION</span>
              <h3>Edit {editingSavedRecord.filename}</h3>
              <p>Changes update the structured database record. The source file remains unchanged.</p>
            </div>
            <button type="button" onClick={() => setEditingSavedRecord(null)}>Close</button>
          </div>
          <textarea
            className="saved-record-json-editor"
            value={savedFieldsText}
            onChange={(event) => setSavedFieldsText(event.target.value)}
            rows={18}
            spellCheck="false"
            aria-label="Edit saved extracted fields as JSON"
          />
          <div className="record-form-actions">
            <button type="button" className="secondary-action"
              onClick={() => setEditingSavedRecord(null)}>Cancel</button>
            <button type="button" className="primary-action"
              onClick={saveExistingRecord} disabled={updatingSavedRecord}>
              {updatingSavedRecord ? 'Saving...' : 'Save changes'}
            </button>
          </div>
        </div>
      )}

      <p className="workspace-footnote">
        Documents are stored by the backend. Indexing and retrieval use your existing embedding model and FAISS vector store.
      </p>
    </section>
  )
}

// EXPENSES PAGE
function ExpensesPage({ expenseData, expenseLoading, expenseError, formatCurrency }) {
  if (expenseLoading) return <section className="workspace-page"><p>Loading expenses...</p></section>
  if (expenseError) return <section className="workspace-page"><p className="notice">Unable to load expenses: {expenseError}</p></section>
  if (!expenseData) return <section className="workspace-page"><p>No expense data available.</p></section>

  const entries = Object.entries(expenseData)
  const total = entries.reduce((sum, [, amount]) => sum + Number(amount), 0)

  return (
    <section className="workspace-page">
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">FINANCIAL MANAGEMENT</span>
          <h1>Expenses</h1>
          <p>Review spending across your recorded expense categories.</p>
        </div>
      </div>
      <div className="document-summary">
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Total Expenses</span>
          <strong>{formatCurrency(total)}</strong>
        </div>
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Categories</span>
          <strong>{entries.length}</strong>
        </div>
      </div>
      <div className="workspace-panel document-library">
        <div className="panel-heading">
          <h3>Expenses by Category</h3>
          <span className="panel-tag">Database overview</span>
        </div>
        {entries.length === 0 ? (
          <p>No expense categories found.</p>
        ) : (
          <div className="records-table-wrapper">
            <table className="records-table">
              <thead><tr><th>Category</th><th>Amount</th><th>Share</th></tr></thead>
              <tbody>
                {entries.map(([category, amount]) => (
                  <tr key={category}>
                    <td>{category}</td>
                    <td>{formatCurrency(amount)}</td>
                    <td>{total > 0 ? `${Math.round((Number(amount) / total) * 100)}%` : '0%'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

// INVOICES PAGE
function InvoicesPage({ invoiceData, invoiceLoading, invoiceError, formatCurrency }) {
  if (invoiceLoading) return <p>Loading invoices...</p>
  if (invoiceError) return <p>Unable to load invoices: {invoiceError}</p>
  if (!invoiceData) return <p>No invoice data available.</p>

  const invoices = invoiceData.all_invoice_details || []

  return (
    <section className="workspace-page invoices-screen">
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">FINANCIAL MANAGEMENT</span>
          <h1>Invoices</h1>
          <p>View all confirmed uploaded invoices and their outstanding status.</p>
        </div>
      </div>

      <div className="document-summary">
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Total Invoices</span>
          <strong>{invoiceData.total_invoices ?? invoices.length}</strong>
        </div>
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Pending Invoices</span>
          <strong>{invoiceData.total_pending_invoices ?? 0}</strong>
        </div>
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Pending Amount</span>
          <strong>{formatCurrency(invoiceData.total_pending_amount)}</strong>
        </div>
        <div className="workspace-panel document-summary-card">
          <span className="summary-label">Overdue Invoices</span>
          <strong>{invoiceData.overdue_invoice_count ?? 0}</strong>
        </div>
      </div>

      <div className="workspace-panel document-library">
        <div className="panel-heading">
          <h3>All Invoices</h3>
          <span className="panel-tag">{invoices.length} records</span>
        </div>
        {invoices.length === 0 ? (
          <div className="company-table-state">No confirmed invoices found. Upload and confirm an invoice in Document Intelligence.</div>
        ) : (
          <div className="records-table-wrapper">
            <table className="records-table">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Vendor</th>
                  <th>Customer</th>
                  <th>Invoice amount</th>
                  <th>Outstanding</th>
                  <th>Due date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice, index) => (
                  <tr key={`${invoice.invoice_number}-${index}`}>
                    <td>{invoice.invoice_number}</td>
                    <td>{invoice.company || '—'}</td>
                    <td>{invoice.customer_name || '—'}</td>
                    <td>{formatCurrency(invoice.amount)}</td>
                    <td>{formatCurrency(invoice.outstanding_amount)}</td>
                    <td>{invoice.due_date || '—'}</td>
                    <td><span className={`record-type ${invoice.status}`}>{invoice.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}


// LIVEKIT VOICE ASSISTANT
function VoiceAssistant() {
  const [callStatus, setCallStatus] = useState('Ready to assist')
  const [assistantState, setAssistantState] = useState('idle')
  const [isConnected, setIsConnected] = useState(false)
  const [isUserSpeaking, setIsUserSpeaking] = useState(false)
  const [callError, setCallError] = useState('')
  const [conversation, setConversation] = useState([])
  const [textDraft, setTextDraft] = useState('')
  const [isSendingText, setIsSendingText] = useState(false)
  const agentReadyRef = useRef(false)
  const agentReadyResolverRef = useRef(null)
  const roomRef = useRef(null)
  const microphoneTrackRef = useRef(null)
  const audioElementsRef = useRef(new Map())
  const activeTurnIdRef = useRef(null)
  const activeTurnHasResponseRef = useRef(false)
  const committedTranscriptRef = useRef('')
  const resultPanelRef = useRef(null)

  // Deepgram may deliver a long utterance as several transcript segments.
  // Merge final segments (and interim previews) instead of replacing the
  // question with only the latest segment.
  const mergeTranscriptText = (baseText, incomingText) => {
    const base = (baseText || '').trim()
    const incoming = (incomingText || '').trim()
    if (!incoming) return base
    if (!base) return incoming

    const baseLower = base.toLowerCase()
    const incomingLower = incoming.toLowerCase()

    // Some STT events contain a cumulative transcript rather than a new segment.
    if (incomingLower.startsWith(baseLower)) return incoming
    if (baseLower.endsWith(incomingLower)) return base
    if (baseLower.startsWith(incomingLower)) return base

    const baseWords = base.split(/\s+/)
    const incomingWords = incoming.split(/\s+/)
    const maxOverlap = Math.min(baseWords.length, incomingWords.length)
    let overlap = 0

    for (let count = maxOverlap; count > 0; count -= 1) {
      const left = baseWords.slice(-count).join(' ').toLowerCase()
      const right = incomingWords.slice(0, count).join(' ').toLowerCase()
      if (left === right) {
        overlap = count
        break
      }
    }

    const remaining = incomingWords.slice(overlap).join(' ')
    return remaining ? `${base} ${remaining}` : base
  }

  const ensureActiveTurn = () => {
    let turnId = activeTurnIdRef.current
    if (!turnId || activeTurnHasResponseRef.current) {
      turnId = `turn-${Date.now()}`
      activeTurnIdRef.current = turnId
      activeTurnHasResponseRef.current = false
      committedTranscriptRef.current = ''
      setConversation((current) => [
        ...current,
        {
          id: turnId,
          question: '',
          displayResponse: '',
          voiceResponse: '',
          pending: true,
        },
      ])
    }
    return turnId
  }

  const updateTranscript = (text, isFinal) => {
    const turnId = ensureActiveTurn()
    const displayedText = mergeTranscriptText(
      committedTranscriptRef.current,
      text
    )

    if (isFinal) {
      committedTranscriptRef.current = displayedText
    }

    setConversation((current) =>
      current.map((turn) =>
        turn.id === turnId ? { ...turn, question: displayedText } : turn
      )
    )
  }

  const updateActiveTurn = (field, value) => {
    const turnId = ensureActiveTurn()
    setConversation((current) =>
      current.map((turn) =>
        turn.id === turnId ? { ...turn, [field]: value } : turn
      )
    )
  }

  const handleAgentMessage = (payload) => {
    try {
      const message = JSON.parse(new TextDecoder().decode(payload))

      if (message.type === 'agent_ready') {
        agentReadyRef.current = true
        if (agentReadyResolverRef.current) {
          agentReadyResolverRef.current()
          agentReadyResolverRef.current = null
        }
      } else if (message.type === 'status') {
        const nextState = ['listening', 'thinking', 'speaking', 'ready'].includes(message.status)
          ? message.status
          : null

        if (nextState) {
          setAssistantState(nextState)
          setCallStatus(
            nextState === 'listening' ? 'Listening — speak now'
              : nextState === 'thinking' ? 'Thinking — analysing your request'
                : nextState === 'ready' ? 'Chat ready'
                  : 'Responding — speaking'
          )
          if (nextState !== 'listening') setIsUserSpeaking(false)
        }
      } else if (message.type === 'transcript' && message.text) {
        updateTranscript(message.text, Boolean(message.is_final))
        if (message.is_final) {
          setAssistantState('thinking')
          setCallStatus('Thinking — analysing your request')
          setIsUserSpeaking(false)
        }
      } else if (message.type === 'display_response' && message.text) {
        updateActiveTurn('displayResponse', message.text)
      } else if (message.type === 'voice_response' && message.text) {
        updateActiveTurn('pending', false)
        activeTurnHasResponseRef.current = true
      } else if (message.type === 'text_response' && message.request_id) {
        setConversation((current) => current.map((turn) =>
          turn.id === message.request_id
            ? { ...turn, displayResponse: message.text || '', sourceDetails: message.details || '', pending: false, source: 'text' }
            : turn
        ))
        setIsSendingText(false)
      } else if (message.type === 'text_error' && message.request_id) {
        setConversation((current) => current.map((turn) =>
          turn.id === message.request_id
            ? { ...turn, error: message.text || 'Unable to process this message.', pending: false }
            : turn
        ))
        setIsSendingText(false)
      } else if (message.type === 'ended') {
        stopConversation()
      } else if (message.type === 'error' && message.text) {
        setCallError(message.text)
        setAssistantState('listening')
        setCallStatus('Something went wrong')
      }
    } catch (error) {
      console.warn('Ignored an unrecognised LiveKit data message:', error)
    }
  }

  const stopConversation = async () => {
    const room = roomRef.current
    roomRef.current = null

    if (room) {
      room.removeAllListeners()
      await room.disconnect()
    }

    if (microphoneTrackRef.current) {
      microphoneTrackRef.current.stop()
      microphoneTrackRef.current = null
    }

    audioElementsRef.current.forEach((element) => {
      element.pause()
      element.srcObject = null
      element.remove()
    })
    audioElementsRef.current.clear()

    activeTurnIdRef.current = null
    activeTurnHasResponseRef.current = false
    committedTranscriptRef.current = ''
    agentReadyRef.current = false
    setConversation([])
    setIsConnected(false)
    setIsUserSpeaking(false)
    setAssistantState('idle')
    setCallStatus('Ready to assist')
  }

  const startConversation = async (publishMicrophone = true) => {
    setCallError('')
    setConversation([])
    activeTurnIdRef.current = null
    activeTurnHasResponseRef.current = false
    committedTranscriptRef.current = ''
    setIsUserSpeaking(false)
    setAssistantState('thinking')
    setCallStatus('Connecting...')
    agentReadyRef.current = false

    try {
      const tokenResponse = await fetch('http://127.0.0.1:8000/livekit/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_name: `finance-room-${crypto.randomUUID()}` }),
      })

      const tokenData = await tokenResponse.json()
      if (!tokenResponse.ok) {
        throw new Error(tokenData.detail || 'Unable to obtain LiveKit access token')
      }

      const room = new Room()
      roomRef.current = room

      room.on(RoomEvent.DataReceived, (payload) => {
        handleAgentMessage(payload)
      })

      // Local-speaker activity moves the orb as soon as microphone speech is detected.
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const localIsSpeaking = speakers.some(
          (speaker) => speaker.identity === room.localParticipant.identity
        )
        setIsUserSpeaking(localIsSpeaking)
        if (localIsSpeaking) {
          setCallStatus((current) =>
            current.startsWith('Thinking') || current.startsWith('Responding')
              ? current
              : 'Listening — capturing your question'
          )
        }
      })

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== Track.Kind.Audio) return

        const audioElement = track.attach()
        audioElement.autoplay = true
        audioElement.setAttribute('playsinline', 'true')
        document.body.appendChild(audioElement)
        audioElementsRef.current.set(track.sid, audioElement)
        audioElement.play().catch(() => {
          setCallError('Audio playback was blocked. Please allow audio playback and try again.')
        })
      })

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach((element) => {
          element.pause()
          element.srcObject = null
          element.remove()
        })
        audioElementsRef.current.delete(track.sid)
      })

      room.on(RoomEvent.Disconnected, () => {
        setIsConnected(false)
        setIsUserSpeaking(false)
        setAssistantState('idle')
        setCallStatus('Disconnected')
      })

      await room.connect(tokenData.server_url, tokenData.participant_token)

      if (publishMicrophone) {
        const microphoneTrack = await createLocalAudioTrack()
        console.log('Microphone settings:', microphoneTrack.mediaStreamTrack.getSettings())
        microphoneTrackRef.current = microphoneTrack
        await room.localParticipant.publishTrack(microphoneTrack)
      }

      setIsConnected(true)
      setAssistantState(publishMicrophone ? 'listening' : 'ready')
      setCallStatus(publishMicrophone ? 'Listening — speak now' : 'Chat connected')
      return room
    } catch (error) {
      await stopConversation()
      setCallError(error.message || 'Unable to connect to the voice assistant.')
      setCallStatus('Connection failed')
    }
  }

  const waitForAgentReady = () => {
    if (agentReadyRef.current) return Promise.resolve()
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        if (agentReadyResolverRef.current === onReady) agentReadyResolverRef.current = null
        reject(new Error('The finance assistant is still connecting. Please try sending again.'))
      }, 15000)
      const onReady = () => {
        window.clearTimeout(timeout)
        resolve()
      }
      agentReadyResolverRef.current = onReady
    })
  }

  const enableVoiceInput = async () => {
    try {
      const room = roomRef.current
      if (!room || room.state !== 'connected') {
        await startConversation(true)
        return
      }
      const microphoneTrack = await createLocalAudioTrack()
      microphoneTrackRef.current = microphoneTrack
      await room.localParticipant.publishTrack(microphoneTrack)
      setAssistantState('listening')
      setCallStatus('Listening — speak now')
    } catch (error) {
      setCallError(error.message || 'Unable to enable microphone access.')
    }
  }

  const sendTextMessage = async (event) => {
    event.preventDefault()
    const question = textDraft.trim()
    if (!question || isSendingText) return

    const requestId = `text-${crypto.randomUUID()}`
    setTextDraft('')
    setIsSendingText(true)
    setCallError('')
    setConversation((current) => [...current, {
      id: requestId,
      question,
      displayResponse: '',
      voiceResponse: '',
      pending: true,
      source: 'text',
    }])

    try {
      let room = roomRef.current
      if (!room || room.state !== 'connected') {
        room = await startConversation(false)
      }
      if (!room) throw new Error('Unable to connect to the finance assistant.')
      await waitForAgentReady()

      const payload = new TextEncoder().encode(JSON.stringify({
        type: 'text_query',
        request_id: requestId,
        text: question,
      }))
      await room.localParticipant.publishData(payload, {
        reliable: true,
        topic: 'finance-assistant-input',
      })
      setCallStatus('Analysing your message')
    } catch (error) {
      setConversation((current) => current.map((turn) =>
        turn.id === requestId
          ? { ...turn, error: error.message || 'Unable to send your message.', pending: false }
          : turn
      ))
      setIsSendingText(false)
      setCallError(error.message || 'Unable to send your message.')
    }
  }

  const renderFinanceContent = (content) => {
    const lines = String(content || '').replace(/\r/g, '').replace(/\\n/g, '\n').split('\n').filter((line) => line.trim())
    return lines.map((rawLine, index) => {
      const line = rawLine.trim()
      const heading = line.match(/^#{1,4}\s*(.+)$/) || line.match(/^\*\*(.+?)\*\*:?$/)
      const metric = line.match(/^(?:[-*]\s*)?\*\*(.+?)\*\*\s*[:—-]\s*(.+)$/)
      const bullet = line.match(/^[-*•]\s+(.+)$/)
      const clean = (value) => value.replace(/\*\*(.*?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
      if (metric) return <div className="finance-result-metric" key={index}><span>{clean(metric[1])}</span><strong>{clean(metric[2])}</strong></div>
      if (heading) return <h4 className="finance-result-heading" key={index}>{clean(heading[1]).replace(/:$/, '')}</h4>
      if (bullet) return <div className="finance-result-bullet" key={index}><span />{clean(bullet[1])}</div>
      return <p className="finance-result-paragraph" key={index}>{clean(line)}</p>
    })
  }

  const extractStructuredJson = (source) => {
    const blocks = []
    let start = -1
    let depth = 0
    let inString = false
    let escaped = false

    for (let index = 0; index < source.length; index += 1) {
      const char = source[index]

      if (start === -1) {
        if (char === '{' || char === '[') {
          start = index
          depth = 1
          inString = false
          escaped = false
        }
        continue
      }

      if (inString) {
        if (escaped) escaped = false
        else if (char === '\\') escaped = true
        else if (char === '"') inString = false
        continue
      }

      if (char === '"') {
        inString = true
      } else if (char === '{' || char === '[') {
        depth += 1
      } else if (char === '}' || char === ']') {
        depth -= 1
        if (depth === 0) {
          const jsonText = source.slice(start, index + 1)
          try {
            blocks.push(JSON.parse(jsonText))
          } catch {
            // Ignore malformed fragments and keep searching for later valid JSON.
          }
          start = -1
        }
      }
    }

    return blocks
  }

  const renderStructuredValue = (value, label = 'Details', path = 'root') => {
    const humanize = (key) => String(key)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (character) => character.toUpperCase())

    if (value === null || value === undefined || value === '') {
      return (
        <div className="finance-result-metric" key={path}>
          <span>{humanize(label)}</span><strong>—</strong>
        </div>
      )
    }

    if (Array.isArray(value)) {
      return (
        <section className="finance-structured-section" key={path}>
          <h4 className="finance-result-heading">{humanize(label)}</h4>
          {value.length === 0
            ? <p className="finance-result-paragraph">No entries available.</p>
            : value.map((item, index) => (
              <div className="finance-structured-item" key={`${path}-${index}`}>
                {item !== null && typeof item === 'object'
                  ? renderStructuredValue(item, `Entry ${index + 1}`, `${path}-${index}`)
                  : <div className="finance-result-bullet"><span />{String(item)}</div>}
              </div>
            ))}
        </section>
      )
    }

    if (typeof value === 'object') {
      const entries = Object.entries(value)
      return (
        <section className="finance-structured-section" key={path}>
          {label !== 'Details' && <h4 className="finance-result-heading">{humanize(label)}</h4>}
          {entries.length === 0
            ? <p className="finance-result-paragraph">No details available.</p>
            : entries.map(([key, child]) => (
              child !== null && typeof child === 'object'
                ? renderStructuredValue(child, key, `${path}-${key}`)
                : (
                  <div className="finance-result-metric" key={`${path}-${key}`}>
                    <span>{humanize(key)}</span>
                    <strong>{child === null || child === undefined || child === '' ? '—' : String(child)}</strong>
                  </div>
                )
            ))}
        </section>
      )
    }

    return (
      <div className="finance-result-metric" key={path}>
        <span>{humanize(label)}</span><strong>{String(value)}</strong>
      </div>
    )
  }

  const renderRetrievedResults = (content) => {
    const rawContent = String(content || '').replace(/\\n/g, '\n')

    // Uploaded invoice records arrive as a readable header followed by JSON.
    // Parse that payload and render it as invoice UI instead of exposing raw JSON.
    const invoiceMarker = 'Extracted invoice fields:'
    const invoiceMarkerIndex = rawContent.indexOf(invoiceMarker)
    if (invoiceMarkerIndex !== -1) {
      const jsonText = rawContent.slice(invoiceMarkerIndex + invoiceMarker.length).trim()
      const jsonStart = jsonText.indexOf('{')
      if (jsonStart !== -1) {
        try {
          const fields = JSON.parse(jsonText.slice(jsonStart))
          const formatMoney = (value) => value == null || value === ''
            ? '—'
            : new Intl.NumberFormat('en-IN', {
              style: 'currency', currency: fields.currency || 'INR',
              maximumFractionDigits: 2,
            }).format(Number(value))
          const formatDate = (value) => {
            if (!value) return '—'
            const date = new Date(value)
            return Number.isNaN(date.getTime())
              ? value
              : date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
          }
          const lineItems = Array.isArray(fields.line_items) ? fields.line_items : []
          const invoiceNumber = fields.invoice_number || 'Invoice details'
          const uploadedAt = rawContent.match(/Uploaded at:\s*([^\n]+)/)?.[1]?.trim()
          const vendorAddress = fields.vendor_address
          const customerAddress = fields.customer_address
          const detailRows = [
            ['Invoice date', formatDate(fields.invoice_date)],
            ['Due date', formatDate(fields.due_date)],
            ['Payment terms', fields.payment_terms || '—'],
            ['Payment method', fields.payment_method || '—'],
            ['Vendor GSTIN', fields.vendor_gstin || '—'],
            ['Customer GSTIN', fields.customer_gstin || '—'],
          ]

          return (
            <div className="retrieved-results invoice-result">
              <div className="invoice-result-topline">
                <div>
                  <span className="invoice-result-kicker">INVOICE</span>
                  <h3>{invoiceNumber}</h3>
                  <p>{rawContent.match(/Filename:\s*([^\n]+)/)?.[1]?.trim() || 'Uploaded invoice'}</p>
                </div>
                <span className="invoice-result-status">Confirmed document</span>
              </div>

              <div className="invoice-parties-grid">
                <div className="invoice-info-card">
                  <span>FROM · VENDOR</span>
                  <strong>{fields.vendor_name || '—'}</strong>
                  {vendorAddress && <p>{vendorAddress}</p>}
                  {fields.vendor_email && <p>{fields.vendor_email}</p>}
                  {fields.contact_person && <p>Contact: {fields.contact_person}</p>}
                </div>
                <div className="invoice-info-card">
                  <span>BILL TO · CUSTOMER</span>
                  <strong>{fields.customer_name || '—'}</strong>
                  {customerAddress && <p>{customerAddress}</p>}
                </div>
              </div>

              <div className="invoice-detail-grid">
                {detailRows.filter(([, value]) => value !== '—').map(([label, value]) => (
                  <div className="invoice-detail-item" key={label}>
                    <span>{label}</span><strong>{value}</strong>
                  </div>
                ))}
              </div>

              <div className="invoice-line-items">
                <div className="invoice-section-heading">
                  <h4>Line items</h4><span>{lineItems.length} item{lineItems.length === 1 ? '' : 's'}</span>
                </div>
                {lineItems.length ? (
                  <div className="records-table-wrapper">
                    <table className="records-table invoice-items-table">
                      <thead><tr><th>Description</th><th>Qty</th><th>Unit price</th><th>Amount</th></tr></thead>
                      <tbody>
                        {lineItems.map((item, index) => (
                          <tr key={`${index}-${item.description || 'item'}`}>
                            <td>{item.description || '—'}</td>
                            <td>{item.quantity ?? '—'}</td>
                            <td>{formatMoney(item.unit_price)}</td>
                            <td>{formatMoney(item.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="finance-result-paragraph">No line items were extracted.</p>}
              </div>

              <div className="invoice-totals">
                <div><span>Subtotal</span><strong>{formatMoney(fields.subtotal)}</strong></div>
                {fields.discount != null && <div><span>Discount</span><strong>−{formatMoney(fields.discount)}</strong></div>}
                {fields.cgst != null && <div><span>CGST</span><strong>{formatMoney(fields.cgst)}</strong></div>}
                {fields.sgst != null && <div><span>SGST</span><strong>{formatMoney(fields.sgst)}</strong></div>}
                {fields.igst != null && <div><span>IGST</span><strong>{formatMoney(fields.igst)}</strong></div>}
                {fields.shipping != null && <div><span>Shipping</span><strong>{formatMoney(fields.shipping)}</strong></div>}
                <div className="invoice-grand-total"><span>Grand total</span><strong>{formatMoney(fields.grand_total)}</strong></div>
                <div><span>Amount paid</span><strong>{formatMoney(fields.amount_paid)}</strong></div>
                <div className="invoice-balance-due"><span>Balance due</span><strong>{formatMoney(fields.balance_due)}</strong></div>
              </div>
              {uploadedAt && <p className="invoice-uploaded-at">Uploaded {formatDate(uploadedAt)}</p>}
            </div>
          )
        } catch (error) {
          console.warn('Unable to format uploaded invoice result; showing readable fallback.', error)
        }
      }
    }

    // Research reports are returned as readable text by the Research Agent.
    // Convert the report's numbered sections and financial findings into a
    // structured report view while preserving the original figures and wording.
    if (/Research Agent Results?:/i.test(rawContent)) {
      const researchMarkerIndex = rawContent.search(/Research Agent Results?:/i)
      const precedingAgentContent = rawContent.slice(0, researchMarkerIndex).trim()
      const reportText = rawContent.slice(researchMarkerIndex)
      const lines = reportText
        .replace(/\r/g, '')
        .replace(/\\n/g, '\n')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .filter((line) => !/^Research Agent Results?:?$/i.test(line))
        .filter((line) => !/^Research result\s*\d+\s*:?.*$/i.test(line))

      const cleanLine = (line) => line
        .replace(/^[-*•]\s*/, '')
        .replace(/^\d+\.\s*/, '')
        .replace(/\*\*/g, '')
        .replace(/`/g, '')
        .trim()

      const companyLine = lines.find((line) => /company and reporting period\s*:/i.test(line))
      const companyDetails = companyLine
        ? cleanLine(companyLine.replace(/^.*?company and reporting period\s*:\s*/i, ''))
        : ''

      const findingsStart = lines.findIndex((line) => /requested financial findings\s*:?$/i.test(cleanLine(line)))
      const sourcesStart = lines.findIndex((line) => /supporting (?:pdf )?filenames?\s*:/i.test(cleanLine(line)))
      const missingStart = lines.findIndex((line) => /missing requested .*findings?\s*:/i.test(cleanLine(line)))

      const findingLines = findingsStart >= 0
        ? lines.slice(findingsStart + 1, [sourcesStart, missingStart, lines.length].filter((n) => n > findingsStart).sort((a, b) => a - b)[0])
        : []

      const headlineMetrics = []
      const metricLabels = new Set()
      const breakdowns = []
      let activeBreakdown = null

      findingLines.forEach((rawLine) => {
        const line = cleanLine(rawLine)
        const metricMatch = line.match(/^(Total Revenue|Total Operating Expenses|Total Expenses|Net Operating Difference|Net Profit|Operating Profit|Gross Profit)\s*[:—-]\s*(.+)$/i)
        if (metricMatch) {
          const label = metricMatch[1].trim()
          const fullValue = metricMatch[2].trim()
          // Keep KPI cards concise: show the amount only and move any
          // explanatory wording/formula into the findings section.
          const amountMatch = fullValue.match(/^((?:₹|INR\s*)?[\d,]+(?:\.\d{1,2})?)(.*)$/i)
          const amount = amountMatch ? amountMatch[1].trim() : fullValue
          const explanation = amountMatch ? amountMatch[2].trim().replace(/^[-:;,]+\s*/, '') : ''
          const normalizedLabel = label.toLowerCase().replace(/\s+/g, ' ')

          if (!metricLabels.has(normalizedLabel)) {
            metricLabels.add(normalizedLabel)
            headlineMetrics.push({ label, value: amount })
          }

          if (explanation) {
            breakdowns.push({ title: 'Additional findings', items: [explanation] })
          }
          activeBreakdown = null
          return
        }

        const sectionMatch = line.match(/^(.{2,70}breakdown)\s*:?\s*$/i)
        if (sectionMatch) {
          activeBreakdown = { title: sectionMatch[1], items: [] }
          breakdowns.push(activeBreakdown)
          return
        }

        if (activeBreakdown) {
          activeBreakdown.items.push(line)
        } else if (line) {
          breakdowns.push({ title: 'Additional findings', items: [line] })
        }
      })

      const sourceLine = sourcesStart >= 0 ? cleanLine(lines[sourcesStart]) : ''
      const sourceValue = sourceLine.replace(/^supporting (?:pdf )?filenames?\s*:\s*/i, '').trim()
      const missingLine = missingStart >= 0 ? cleanLine(lines[missingStart]) : ''
      const missingValue = missingLine.replace(/^missing requested .*findings?\s*:\s*/i, '').trim()

      return (
        <div className="retrieved-results research-report">
          {precedingAgentContent && (
            <div className="research-finance-context">
              {renderFinanceContent(precedingAgentContent)}
            </div>
          )}
          <div className="research-report-heading">
            <div>
              <span className="research-report-kicker">RESEARCH REPORT</span>
              <h3>{companyDetails || 'Document findings'}</h3>
            </div>
            <span className="research-report-badge">Source-backed</span>
          </div>

          {headlineMetrics.length > 0 && (
            <div className="retrieved-metrics research-report-metrics">
              {headlineMetrics.map((metric, index) => (
                <div className="retrieved-metric-card" key={`${metric.label}-${index}`}>
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                </div>
              ))}
            </div>
          )}

          {breakdowns.map((section, index) => (
            <section className="research-findings-section" key={`${section.title}-${index}`}>
              <h4>{section.title}</h4>
              <div className="research-findings-list">
                {section.items.map((item, itemIndex) => (
                  <div className="research-finding-row" key={`${index}-${itemIndex}`}>
                    <span className="research-finding-dot" />
                    <p>{item}</p>
                  </div>
                ))}
              </div>
            </section>
          ))}

          {(sourceValue || missingValue) && (
            <div className="research-evidence-grid">
              {sourceValue && (
                <div className="research-evidence-card">
                  <span>SUPPORTING DOCUMENT</span>
                  <strong>{sourceValue}</strong>
                </div>
              )}
              {missingValue && (
                <div className="research-evidence-card">
                  <span>DATA AVAILABILITY</span>
                  <strong>{missingValue}</strong>
                </div>
              )}
            </div>
          )}
        </div>
      )
    }

    // Generic structured-data fallback: supports any JSON-shaped agent/tool
    // response (including multiple uploaded documents), not only invoices.
    const structuredBlocks = extractStructuredJson(rawContent)
    if (structuredBlocks.length) {
      return (
        <div className="retrieved-text-results finance-structured-results">
          {structuredBlocks.map((block, index) => (
            <div className="finance-structured-record" key={`structured-${index}`}>
              {structuredBlocks.length > 1 && (
                <h4 className="finance-result-heading">Record {index + 1}</h4>
              )}
              {renderStructuredValue(block, 'Details', `record-${index}`)}
            </div>
          ))}
        </div>
      )
    }

    const normalized = rawContent.replace(/\s+/g, ' ')
    const metricDefinitions = [
      { key: 'revenue', label: 'Total Revenue', pattern: /(?:total\s+revenue|current\s+revenue|revenue)[^₹]{0,90}₹\s*([\d,]+(?:\.\d{1,2})?)/i },
      { key: 'expenses', label: 'Total Expenses', pattern: /(?:total\s+expenses?|current\s+expenses?|expenses?)[^₹]{0,90}₹\s*([\d,]+(?:\.\d{1,2})?)/i },
      { key: 'profit', label: 'Net Profit', pattern: /(?:net\s+profit|net\s+financial\s+difference)[^₹]{0,90}₹\s*([\d,]+(?:\.\d{1,2})?)/i },
    ]
    const metrics = metricDefinitions.map((metric) => {
      const match = normalized.match(metric.pattern)
      return match ? { ...metric, value: `₹${match[1]}` } : null
    }).filter(Boolean)

    // Keep the compact KPI cards, but never discard the rest of the agent response.
    // Remove only the three headline metric lines from the detail section to avoid
    // showing the same values twice. Categories, invoices, trends, caveats and
    // source notes remain visible below the cards.
    const detailLines = rawContent
      .split('\n')
      .filter((line) => {
        const plainLine = line.replace(/[*#`]/g, '').trim()
        return !/^(?:total revenue|current revenue|revenue|total expenses?|current expenses?|expenses?|net profit|net financial difference)\s*[:—-]/i.test(plainLine)
      })
      .join('\n')
      .trim()

    if (metrics.length) {
      const aggregateOnly = /aggregate|not filtered by reporting period|not separated by reporting period/i.test(normalized)
      return (
        <div className="retrieved-results">
          <div className="retrieved-metrics">
            {metrics.map((metric) => (
              <div className="retrieved-metric-card" key={metric.key}>
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
              </div>
            ))}
          </div>
          {aggregateOnly && <p className="retrieved-results-note">Aggregate totals · Not separated by reporting period</p>}
          {detailLines && (
            <div className="retrieved-text-results">
              {renderFinanceContent(detailLines)}
            </div>
          )}
        </div>
      )
    }

    return <div className="retrieved-text-results">{renderFinanceContent(rawContent)}</div>
  }

  useEffect(() => {
    if (resultPanelRef.current) {
      resultPanelRef.current.scrollTop = resultPanelRef.current.scrollHeight
    }
  }, [conversation])

  useEffect(() => {
    return () => {
      const room = roomRef.current
      if (room) room.disconnect()
      if (microphoneTrackRef.current) microphoneTrackRef.current.stop()
      audioElementsRef.current.forEach((element) => {
        element.pause()
        element.srcObject = null
        element.remove()
      })
      audioElementsRef.current.clear()
    }
  }, [])

  const stateCaption = {
    idle: 'Start a voice conversation with your AI finance employee',
    ready: 'Send a message or start a voice conversation',
    listening: 'Your AI finance employee is listening',
    thinking: 'Your request is being analysed. Please wait...',
    speaking: 'Your AI finance employee is responding',
  }[assistantState]

  const hasConversationLayout = isConnected || conversation.length > 0

  return (
    <section className={`assistant-screen voice-assistant ${hasConversationLayout ? 'has-conversation' : ''} ${isUserSpeaking ? 'user-speaking' : ''}`}>
      <style>{`
        .voice-assistant { min-height:calc(100vh - 110px); display:flex; flex-direction:column; justify-content:flex-start; align-items:stretch; text-align:left; padding:clamp(24px,3vw,42px); box-sizing:border-box; }
        .voice-assistant .assistant-heading { text-align:left; width:100%; max-width:1250px; margin:0 auto; }
        .voice-assistant .assistant-heading h1 { margin-left:0; }
        .voice-workspace { flex:1; display:grid; grid-template-columns:minmax(210px,.62fr) minmax(0,1.7fr); gap:clamp(22px,3vw,42px); align-items:start; width:100%; max-width:1250px; margin:28px auto 0; min-height:0; }
        .voice-visual { display:flex; flex-direction:column; align-items:center; justify-content:flex-start; min-width:0; padding-top:34px; transition:all .55s cubic-bezier(.2,.8,.2,1); }
        .voice-assistant:not(.has-conversation) .voice-workspace { grid-template-columns:1fr; }
        .voice-assistant:not(.has-conversation) .voice-visual { min-height:390px; padding-top:0; }
        .voice-assistant:not(.has-conversation) .orb-area { transform:scale(1.08); }
        .voice-assistant.has-conversation .voice-visual { position:sticky; top:24px; align-self:start; }
        .voice-assistant.has-conversation .orb-area { transform:scale(.68); transform-origin:center top; margin:0 0 -74px; }
        .voice-assistant.user-speaking .orb-area { transform:scale(.72); }
        .voice-assistant .orb-area { transition:transform .3s ease; }
        .voice-assistant .orb-area.listening .orb { animation:voicePulse 2.1s ease-in-out infinite; }
        .voice-assistant .orb-area.thinking .orb { animation:voiceThink 1.15s ease-in-out infinite; }
        .voice-assistant .orb-area.speaking .orb { animation:voiceSpeak .65s ease-in-out infinite alternate; }
        .voice-assistant .orb-area.listening .orb-rings { animation:voiceRing 2s ease-out infinite; }
        .voice-assistant .orb-area.thinking .orb-rings { animation:voiceRing .95s ease-out infinite; }
        .voice-assistant .orb-area.speaking .orb-rings { animation:voiceRing .55s ease-out infinite; }
        .voice-state-caption { color:var(--text-secondary,#9ca3af); text-align:center; margin-top:7px; font-size:13px; }
        .voice-result-panel { width:100%; min-width:0; max-height:calc(100vh - 245px); min-height:360px; overflow-y:auto; align-self:start; position:sticky; top:18px; border:1px solid var(--border-color,rgba(255,255,255,.12)); background:var(--panel-bg,rgba(255,255,255,.035)); border-radius:18px; padding:clamp(20px,2.5vw,32px); box-sizing:border-box; scroll-behavior:smooth; text-align:left; box-shadow:0 16px 45px rgba(0,0,0,.12); }
        .voice-result-panel > .eyebrow { display:block; text-align:left; }
        .voice-result-panel h2 { margin:6px 0 24px; text-align:left; font-size:clamp(20px,2vw,27px); }
        .voice-result-placeholder { color:var(--text-secondary,#9ca3af); line-height:1.7; text-align:left; }
        .voice-turn { padding:0 0 22px; margin:0 0 22px; border-bottom:1px solid var(--border-color,rgba(255,255,255,.1)); }
        .voice-turn:last-child { border-bottom:0; margin-bottom:0; }
        .voice-turn-question { display:block; width:min(82%,680px); box-sizing:border-box; padding:13px 16px; margin:14px 0 20px auto; border:1px solid var(--border-color,rgba(255,255,255,.08)); border-radius:16px 16px 4px 16px; background:rgba(130,150,180,.12); color:var(--text); line-height:1.6; text-align:left; overflow-wrap:anywhere; }
        .voice-turn-question strong { display:block; margin:0 0 6px; text-align:left; color:var(--text-secondary,#aab0bb); font-size:12px; }
        .voice-turn-question > div { display:block; width:100%; max-width:100%; box-sizing:border-box; margin:0; padding:0; white-space:pre-wrap; overflow-wrap:anywhere; word-break:normal; text-align:left; font-size:14px; line-height:1.7; font-weight:400; transform:none; }
        .voice-turn-section { margin-top:12px; padding:18px 20px; border:1px solid var(--border-color,rgba(255,255,255,.08)); border-radius:4px 16px 16px 16px; background:rgba(255,255,255,.025); }
        .voice-turn-section strong { display:block; margin-bottom:10px; font-size:12px; letter-spacing:.02em; color:var(--text-secondary,#aab0bb); }
        .voice-turn-answer { white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.8; font-size:14px; text-align:left; }
        .voice-controls { display:flex; flex-direction:column; align-items:center; gap:12px; margin-top:22px; }
        @keyframes voicePulse { 0%,100% { transform:scale(1); filter:brightness(1); } 50% { transform:scale(1.045); filter:brightness(1.18); } }
        @keyframes voiceThink { 0%,100% { transform:scale(.97) rotate(-2deg); } 50% { transform:scale(1.04) rotate(2deg); } }
        @keyframes voiceSpeak { from { transform:scale(.96); } to { transform:scale(1.07); } }
        @keyframes voiceRing { 0% { opacity:.65; transform:scale(.94); } 100% { opacity:0; transform:scale(1.22); } }
        @media(max-width:760px) {
          .voice-assistant { padding:22px 16px; }
          .voice-workspace,.voice-assistant.has-conversation .voice-workspace { grid-template-columns:1fr; gap:8px; margin-top:16px; }
          .voice-assistant.has-conversation .voice-visual { position:static; padding-top:0; }
          .voice-assistant.has-conversation .orb-area { transform:scale(.58); transform-origin:center top; margin:0 0 -105px; }
          .voice-assistant.user-speaking .orb-area { transform:scale(.62); }
          .voice-result-panel { max-height:55vh; min-height:240px; position:relative; top:auto; }
          .voice-turn-question { width:min(94%,680px); }
        }
        .voice-assistant { --assistant-surface:var(--card); --assistant-border:var(--border); }
        .voice-assistant .voice-workspace { grid-template-columns:minmax(210px,.55fr) minmax(0,1.8fr); gap:clamp(24px,3vw,44px); }
        .voice-assistant .voice-result-panel { max-height:calc(100dvh - 235px); min-height:430px; display:flex; flex-direction:column; background:var(--card); border:1px solid var(--border); border-radius:22px; padding:clamp(20px,2.4vw,30px); box-shadow:0 18px 55px rgba(0,0,0,.09); }
        .voice-assistant .voice-result-panel h2 { margin-bottom:18px; letter-spacing:-.7px; }
        .voice-assistant .voice-turn { padding-bottom:24px; margin-bottom:24px; }
        .voice-assistant .voice-turn-question { width:min(86%,720px); background:var(--hover); border:1px solid var(--border); border-radius:17px 17px 5px 17px; padding:15px 18px; }
        .voice-assistant .voice-turn-section { margin-top:12px; padding:20px; border:1px solid var(--border); border-radius:5px 17px 17px 17px; background:color-mix(in srgb,var(--background) 55%,var(--card)); }
        .voice-assistant .voice-turn-section > strong { text-transform:uppercase; letter-spacing:.09em; font-size:10px; }
        .finance-result-heading { margin:18px 0 10px; font-size:13px; letter-spacing:.01em; color:var(--text); }
        .finance-structured-section { margin:12px 0; padding:12px; border:1px solid var(--border); border-radius:12px; background:var(--card); }
        .finance-structured-record { margin:10px 0; }
        .finance-structured-item { margin:10px 0; padding:10px; border:1px solid var(--border); border-radius:10px; }
        .finance-result-metric { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:12px 14px; margin:7px 0; border:1px solid var(--border); border-radius:11px; background:var(--card); }
        .finance-result-metric span { color:var(--muted); font-size:12px; }
        .finance-result-metric strong { color:var(--text); font-size:13px; font-weight:650; text-align:right; }
        .finance-result-paragraph { margin:9px 0; color:var(--text); font-size:13px; line-height:1.75; }
        .finance-result-bullet { display:flex; gap:10px; align-items:flex-start; margin:8px 0; color:var(--text); font-size:12px; line-height:1.7; }
        .finance-result-bullet > span { width:6px; height:6px; margin-top:8px; flex:0 0 6px; border-radius:50%; background:var(--muted); }
        .voice-chat-composer { position:sticky; bottom:-1px; z-index:2; margin-top:auto; padding:18px 0 0; background:linear-gradient(180deg,transparent,var(--card) 18%); }
        .voice-chat-form { display:flex; align-items:flex-end; gap:10px; padding:9px 10px 9px 17px; border:1px solid var(--border); border-radius:18px; background:var(--background); box-shadow:0 8px 28px rgba(0,0,0,.08); transition:border-color .2s,box-shadow .2s,transform .2s; }
        .voice-chat-form:focus-within { border-color:var(--muted); box-shadow:0 0 0 4px color-mix(in srgb,var(--muted) 12%,transparent),0 12px 32px rgba(0,0,0,.1); transform:translateY(-1px); }
        .voice-chat-form textarea { flex:1; min-width:0; min-height:28px; max-height:120px; resize:vertical; border:0; outline:0; background:transparent; color:var(--text); font:inherit; font-size:13px; line-height:1.6; padding:5px 0; }
        .voice-chat-form textarea::placeholder { color:var(--muted); }
        .voice-chat-send { width:42px; height:42px; flex:0 0 42px; display:grid; place-items:center; border:0; border-radius:13px; background:var(--text); color:var(--background); font-size:19px; cursor:pointer; transition:transform .2s,opacity .2s; }
        .voice-chat-send:hover { transform:translateY(-2px); }
        .voice-chat-send:disabled { opacity:.35; cursor:not-allowed; transform:none; }
        .voice-chat-hint { margin:8px 4px 0; color:var(--muted); font-size:10px; }
        .voice-turn-error { padding:12px 14px; border:1px solid #d9775740; border-radius:11px; color:#c66b50; font-size:12px; }
        .voice-turn-pending { display:flex; align-items:center; gap:9px; color:var(--muted); font-size:12px; padding:12px 4px; }
        .voice-turn-pending::before { content:''; width:7px; height:7px; border-radius:50%; background:currentColor; animation:voicePulse 1s infinite; }
        @media(max-width:760px) { .voice-assistant .voice-workspace { grid-template-columns:1fr; } .voice-assistant .voice-result-panel { min-height:340px; max-height:none; } .voice-chat-composer { position:sticky; bottom:0; } .voice-assistant .voice-turn-question { width:100%; } .finance-result-metric { align-items:flex-start; flex-direction:column; gap:4px; } .finance-result-metric strong { text-align:left; } }
        .invoice-result { display:flex; flex-direction:column; gap:18px; min-width:0; }
        .invoice-result-topline { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; padding-bottom:15px; border-bottom:1px solid var(--border); }
        .invoice-result-kicker,.invoice-info-card > span { color:var(--muted); font-size:10px; font-weight:700; letter-spacing:.1em; }
        .invoice-result-topline h3 { margin:5px 0; color:var(--text); font-size:20px; }
        .invoice-result-topline p,.invoice-info-card p { margin:4px 0 0; color:var(--muted); font-size:12px; line-height:1.6; overflow-wrap:anywhere; }
        .invoice-result-status { flex:0 0 auto; padding:6px 10px; border:1px solid var(--border); border-radius:999px; color:var(--text-secondary); font-size:10px; }
        .invoice-parties-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
        .invoice-info-card { min-width:0; padding:15px; border:1px solid var(--border); border-radius:13px; background:var(--background); }
        .invoice-info-card strong { display:block; margin-top:8px; color:var(--text); font-size:14px; overflow-wrap:anywhere; }
        .invoice-detail-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
        .invoice-detail-item { min-width:0; padding:11px 12px; border:1px solid var(--border); border-radius:11px; }
        .invoice-detail-item span,.invoice-totals span { display:block; color:var(--muted); font-size:11px; }
        .invoice-detail-item strong { display:block; margin-top:5px; color:var(--text); font-size:12px; overflow-wrap:anywhere; }
        .invoice-section-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
        .invoice-section-heading h4 { margin:0; color:var(--text); font-size:14px; }
        .invoice-section-heading span { color:var(--muted); font-size:11px; }
        .invoice-items-table { min-width:560px; }
        .invoice-items-table th,.invoice-items-table td { font-size:12px; }
        .invoice-totals { width:min(100%,420px); margin-left:auto; padding:14px 16px; border:1px solid var(--border); border-radius:13px; background:var(--background); }
        .invoice-totals > div { display:flex; justify-content:space-between; gap:14px; padding:7px 0; }
        .invoice-totals strong { color:var(--text); font-size:12px; text-align:right; }
        .invoice-totals .invoice-grand-total { margin-top:5px; padding-top:12px; border-top:1px solid var(--border); }
        .invoice-totals .invoice-grand-total span,.invoice-totals .invoice-grand-total strong { color:var(--text); font-size:14px; font-weight:750; }
        .invoice-totals .invoice-balance-due { margin-top:4px; padding:11px 12px; border-radius:9px; background:var(--hover); }
        .invoice-totals .invoice-balance-due span,.invoice-totals .invoice-balance-due strong { color:var(--text); font-weight:750; }
        .invoice-uploaded-at { margin:0; color:var(--muted); font-size:10px; }
        @media(max-width:760px) { .invoice-parties-grid { grid-template-columns:1fr; } .invoice-detail-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .invoice-result-topline { flex-direction:column; } }
        .voice-source-details { margin-top:12px; border:1px solid var(--border); border-radius:12px; padding:12px 15px; background:var(--background); }
        .voice-source-details summary { color:var(--muted); font-size:11px; cursor:pointer; font-weight:600; }
        .voice-source-details .voice-turn-answer { padding-top:12px; }
      `}</style>

      <div className="assistant-heading">
        <span className="eyebrow">YOUR FINANCE INTELLIGENCE</span>
        <h1>How can I help you today?</h1>
        <p>Speak with your AI finance employee about financial records, reports, or business data.</p>
      </div>

      <div className="voice-workspace">
        <div className="voice-visual">
          <div className={`orb-area ${assistantState}`}>
            <div className="orb-glow" />
            <div className="orb">
              <div className="orb-inner">
                <div className="orb-core" />
              </div>
            </div>
            <div className="orb-rings ring-one" />
            <div className="orb-rings ring-two" />
          </div>

          <div className="assistant-status">
            <span className={`status-dot ${isConnected ? 'connected' : ''}`} />
            {callStatus}
          </div>
          <div className="voice-state-caption">{stateCaption}</div>

          <div className="voice-controls">
            <button
              className="primary-action"
              type="button"
              onClick={isConnected ? (microphoneTrackRef.current ? stopConversation : enableVoiceInput) : startConversation}
            >
              {isConnected ? (microphoneTrackRef.current ? 'End conversation' : 'Enable microphone') : 'Start voice conversation'}
            </button>
            {callError && <p className="notice">{callError}</p>}
          </div>
        </div>

        {hasConversationLayout && (
          <div className="voice-result-panel" aria-live="polite" ref={resultPanelRef}>
            <span className="eyebrow">FINANCIAL ANALYSIS</span>
            <h2>Financial Results</h2>
            {conversation.length === 0 ? (
              <p className="voice-result-placeholder">
                Start a voice conversation to see retrieved financial results here.
              </p>
            ) : (
              conversation.map((turn, index) => (
                <div className="voice-turn" key={turn.id}>
                  <div className="voice-turn-question">
                    <strong>User</strong>
                    <div>{turn.question || 'Listening...'}</div>
                  </div>

                  {turn.displayResponse && (
                    <div className="retrieved-results-section">
                      <div className="retrieved-results-header">
                        <span className="eyebrow">RETRIEVED RESULTS</span>
                      </div>
                      {renderRetrievedResults(turn.displayResponse)}
                    </div>
                  )}

                  {turn.error && <div className="voice-turn-error">{turn.error}</div>}
                  {turn.pending && !turn.displayResponse && !turn.error && (
                    <div className="voice-turn-pending">Retrieving financial results</div>
                  )}
                  {!turn.pending && !turn.displayResponse && !turn.error && (
                    <p className="voice-result-placeholder">No results were returned for this request.</p>
                  )}
                </div>
              ))
            )}

          </div>
        )}
      </div>
    </section>
  )
}

// MAIN APPLICATION
function App() {
  const [activePage, setActivePage] = useState('AI Assistant')
  const [notice, setNotice] = useState('')
  const [theme, setTheme] = useState(() => {
    try {
      const savedTheme = window.localStorage.getItem('finai-theme')
      return savedTheme === 'light' ? 'light' : 'dark'
    } catch {
      return 'dark'
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem('finai-theme', theme)
    } catch (error) {
      console.warn('Unable to persist theme preference:', error)
    }
  }, [theme])
  const [revenueData, setRevenueData] = useState(null)
  const [revenueLoading, setRevenueLoading] = useState(true)
  const [revenueError, setRevenueError] = useState('')
  const [invoiceData, setInvoiceData] = useState(null)
  const [invoiceLoading, setInvoiceLoading] = useState(true)
  const [invoiceError, setInvoiceError] = useState('')
  const [expenseData, setExpenseData] = useState(null)
  const [expenseLoading, setExpenseLoading] = useState(true)
  const [expenseError, setExpenseError] = useState('')
  const [companyOverview, setCompanyOverview] = useState(null)
  const [companyOverviewLoading, setCompanyOverviewLoading] = useState(true)
  const [companyOverviewError, setCompanyOverviewError] = useState('')
  const [companySearchTerm, setCompanySearchTerm] = useState('')

  useEffect(() => {
    const fetchCompanyOverview = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/finance/company-overview')
        if (!response.ok) throw new Error('Failed to fetch uploaded-company overview')
        setCompanyOverview(await response.json())
      } catch (error) {
        setCompanyOverviewError(error.message)
      } finally {
        setCompanyOverviewLoading(false)
      }
    }
    fetchCompanyOverview()
  }, [])

  useEffect(() => {
    const fetchRevenue = async () => {
      try {
        const response = await fetch(
          'http://127.0.0.1:8000/finance/revenue'
        )

        if (!response.ok) {
          throw new Error('Failed to fetch financial data')
        }

        const data = await response.json()
        setRevenueData(data)
      } catch (error) {
        setRevenueError(error.message)
      } finally {
        setRevenueLoading(false)
      }
    }

    fetchRevenue()
  }, [])

  //fetch Invoices

  useEffect(() => {
    const fetchInvoices = async () => {
      try {
        const response = await fetch(
          'http://127.0.0.1:8000/finance/invoices'
        )

        if (!response.ok) {
          throw new Error('Failed to fetch invoice data')
        }

        const data = await response.json()
        setInvoiceData(data)
      } catch (error) {
        setInvoiceError(error.message)
      } finally {
        setInvoiceLoading(false)
      }
    }

    fetchInvoices()
  }, [])

  // Fetch expense categories
  useEffect(() => {
    const fetchExpenses = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/finance/expenses')
        if (!response.ok) throw new Error('Failed to fetch expense data')
        setExpenseData(await response.json())
      } catch (error) {
        setExpenseError(error.message)
      } finally {
        setExpenseLoading(false)
      }
    }
    fetchExpenses()
  }, [])

  // FINANCIAL RECORDS STATE
  const [records, setRecords] = useState([])
  const [recordLoading, setRecordLoading] = useState(true)
  const [recordError, setRecordError] = useState('')
  const [recordType, setRecordType] = useState('All')
  const [showRecordForm, setShowRecordForm] = useState(false)


  const [newRecord, setNewRecord] = useState({
    title: '',
    type: 'Income',
    amount: '',
    date: new Date().toISOString().split('T')[0],
  })

  const loadTransactions = async () => {
    try {
      setRecordError('')
      const response = await fetch('http://127.0.0.1:8000/finance/transactions')
      if (!response.ok) throw new Error('Failed to load financial records')
      const data = await response.json()
      setRecords(data.map((item) => ({
        id: item.id,
        title: item.description || '',
        type: item.transaction_type === 'income' ? 'Income' : 'Expense',
        amount: item.amount,
        date: item.transaction_date,
      })))
    } catch (error) {
      setRecordError(error.message)
    } finally {
      setRecordLoading(false)
    }
  }

  useEffect(() => {
    loadTransactions()
  }, [])

  const refreshFinancialSummaries = async () => {
    try {
      const [revenueResponse, expenseResponse] = await Promise.all([
        fetch('http://127.0.0.1:8000/finance/revenue'),
        fetch('http://127.0.0.1:8000/finance/expenses'),
      ])
      if (revenueResponse.ok) setRevenueData(await revenueResponse.json())
      if (expenseResponse.ok) setExpenseData(await expenseResponse.json())
    } catch (error) {
      console.error('Unable to refresh financial summaries:', error)
    }
  }

  const handleSaveRecord = async (record) => {
    try {
      setRecordError('')
      const response = await fetch('http://127.0.0.1:8000/finance/transactions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: record.title,
          transaction_type: record.type.toLowerCase(),
          amount: Number(record.amount),
          transaction_date: record.date,
        }),
      })
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Failed to save record')
      }
      await loadTransactions()
      await refreshFinancialSummaries()
      return true
    } catch (error) {
      setRecordError(error.message)
      return false
    }
  }

  const handleUpdateRecord = async (id, record) => {
    try {
      setRecordError('')
      const response = await fetch(`http://127.0.0.1:8000/finance/transactions/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: record.title,
          transaction_type: record.type.toLowerCase(),
          amount: Number(record.amount),
          transaction_date: record.date,
        }),
      })
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Failed to update record')
      }
      await loadTransactions()
      await refreshFinancialSummaries()
      return true
    } catch (error) {
      setRecordError(error.message)
      return false
    }
  }

  const handleDeleteRecord = async (id) => {
    if (!window.confirm('Delete this financial record?')) return
    try {
      setRecordError('')
      const response = await fetch(`http://127.0.0.1:8000/finance/transactions/${id}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Failed to delete record')
      }
      await loadTransactions()
      await refreshFinancialSummaries()
    } catch (error) {
      setRecordError(error.message)
    }
  }

  const navItems = [
    { name: 'Dashboard', icon: '▦' },
    { name: 'AI Assistant', icon: '🎙' },
    { name: 'Document Intelligence', icon: '▱' },
    { name: 'Invoices', icon: '▤' },
  ]

  const formatCurrency = (value) =>
    `₹${Number(value || 0).toLocaleString('en-IN')}`

  const companyReports = companyOverview?.reports || []
  const totalSourceDocuments = companyReports.reduce(
    (sum, report) => sum + Number(report.document_count || 0),
    0
  )
  const filteredCompanyReports = companyReports.filter((report) => {
    const search = companySearchTerm.trim().toLowerCase()
    if (!search) return true
    return [report.company_name, report.reporting_period, report.currency]
      .some((value) => String(value || '').toLowerCase().includes(search))
  })

  const formatCompanyMetric = (metric) => {
    if (metric.value == null) return metric.raw_value || '—'
    const value = Number(metric.value)
    const displayUnit = metric.unit && String(metric.unit).toLowerCase() !== 'currency'
      ? ` ${metric.unit}`
      : ''
    return Number.isFinite(value)
      ? `${value.toLocaleString('en-IN')}${displayUnit}`
      : (metric.raw_value || '—')
  }



  return (
    <div className={`app-container ${theme}`}>
      {/* SIDEBAR */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">✧</div>

          <div>
            <h2>FinAI</h2>
            <span>Finance Intelligence</span>
          </div>
        </div>

        <div className="nav-label">WORKSPACE</div>

        <nav className="navigation">
          {navItems.map((item) => (
            <button
              key={item.name}
              className={`nav-item ${activePage === item.name ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(item.name)
                setNotice('')
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.name}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="connection-status">
            <span className="status-dot" />
            Local AI Environment
          </div>

          <div className="user-profile">
            <div className="avatar">H</div>

            <div>
              <strong>Finance User</strong>
              <span>Administrator</span>
            </div>
          </div>
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="main-content">
        {/* TOPBAR */}
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace /</span>
            <strong>{activePage}</strong>
          </div>

          <div className="topbar-right">
            <span className="system-label">
              <span className="status-dot" />
              System Ready
            </span>

            <button
              className="theme-toggle"
              onClick={() =>
                setTheme((current) =>
                  current === 'dark' ? 'light' : 'dark'
                )
              }
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'
                } mode`}
            >
              {theme === 'dark' ? '☀ Light Mode' : '☾ Dark Mode'}
            </button>

            <div className="top-avatar">H</div>
          </div>
        </header>

        {/* DASHBOARD */}
        {activePage === 'Dashboard' && (
          <section className="dashboard-screen">
            <div className="dashboard-heading">
              <div>
                <span className="eyebrow">MULTI-COMPANY FINANCIAL INTELLIGENCE</span>
                <h1>Dashboard</h1>
                <p>
                  Explore financial information extracted from reports and invoices uploaded across tracked companies.
                </p>

              </div>

              <div className="dashboard-period">
                <span>DATABASE OVERVIEW</span>
                <strong>All recorded data</strong>
              </div>
            </div>

            <div className="company-overview-stats">
              <div className="company-overview-stat">
                <span>Companies tracked</span>
                <strong>{companyOverviewLoading ? '—' : (companyOverview?.total_companies ?? 0)}</strong>
                <small>Across confirmed reports</small>
              </div>
              <div className="company-overview-stat">
                <span>Report records</span>
                <strong>{companyOverviewLoading ? '—' : companyReports.length}</strong>
                <small>Reporting periods available</small>
              </div>
              <div className="company-overview-stat">
                <span>Source documents</span>
                <strong>{companyOverviewLoading ? '—' : totalSourceDocuments}</strong>
                <small>Linked to report records</small>
              </div>
            </div>

            <div className="dashboard-panel company-intelligence-panel">
              <div className="company-intelligence-heading">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">UPLOADED FINANCIAL REPORTS</span>
                    <h3>Company Intelligence Overview</h3>
                    <p className="company-table-subtitle">A quick view of the key figures extracted from each confirmed report.</p>
                  </div>
                  <span className="panel-tag">
                    {companyOverviewLoading
                      ? 'Loading'
                      : `${companyOverview?.total_companies ?? 0} companies`}
                  </span>
                </div>
                <label className="company-search">
                  <span className="sr-only">Search companies or reporting periods</span>
                  <span aria-hidden="true">⌕</span>
                  <input
                    type="search"
                    value={companySearchTerm}
                    onChange={(event) => setCompanySearchTerm(event.target.value)}
                    placeholder="Search companies or periods..."
                    disabled={companyOverviewLoading || !companyReports.length}
                  />
                </label>
              </div>

              {companyOverviewError && (
                <p className="notice">Unable to load company overview: {companyOverviewError}</p>
              )}

              {companyOverviewLoading ? (
                <div className="company-table-state">Loading company financial observations...</div>
              ) : !companyReports.length ? (
                <div className="empty-transactions">
                  <strong>No company financial reports found</strong>
                  <p>Upload and confirm financial reports to see company-level information here.</p>
                </div>
              ) : !filteredCompanyReports.length ? (
                <div className="company-table-state">No companies or reporting periods match your search.</div>
              ) : (
                <div className="records-table-wrapper company-table-wrapper">
                  <table className="records-table company-intelligence-table">
                    <thead>
                      <tr>
                        <th>Company</th>
                        <th>Reporting period</th>
                        <th>Revenue</th>
                        <th>Operating expenses</th>
                        <th>Currency</th>
                        <th>Documents</th>
                        <th><span className="sr-only">More details</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCompanyReports.map((report, index) => {
                        const metrics = report.metrics || []
                        const revenueMetric = metrics.find((metric) => /revenue|total income/i.test(metric.metric_name || ''))
                        const expenseMetric = metrics.find((metric) => /operating expenses|total expenses/i.test(metric.metric_name || ''))
                        return (
                          <tr key={`${report.company_name}-${report.reporting_period}-${report.currency}-${index}`}>
                            <td className="company-name-cell">{report.company_name}</td>
                            <td>{report.reporting_period || '—'}</td>
                            <td className="company-amount-cell">{revenueMetric ? formatCompanyMetric(revenueMetric) : '—'}</td>
                            <td className="company-amount-cell">{expenseMetric ? formatCompanyMetric(expenseMetric) : '—'}</td>
                            <td>{report.currency || '—'}</td>
                            <td>{report.document_count ?? 0}</td>
                            <td>
                              <details className="company-metrics-details">
                                <summary>Details</summary>
                                <div className="company-metrics-popover">
                                  {metrics.length ? metrics.map((metric, metricIndex) => (
                                    <div key={`${metric.metric_name}-${metricIndex}`}>
                                      <span>{metric.metric_name}</span>
                                      <strong>{formatCompanyMetric(metric)}</strong>
                                    </div>
                                  )) : <span>No extracted metrics available.</span>}
                                </div>
                              </details>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="workspace-footnote">
                Figures are shown by company, reporting period, and currency. Different periods and currencies are not added together. Select Details to view all extracted metrics.
              </p>
            </div>

            <div className="dashboard-panel dashboard-invoice-panel">
              <div className="panel-heading dashboard-invoice-heading">
                <div>
                  <span className="eyebrow">INVOICE OVERVIEW</span>
                  <h3>Payment tracking</h3>
                  <p className="company-table-subtitle">A snapshot of pending and overdue invoices recorded in FinAI.</p>
                </div>
                <button
                  type="button"
                  className="panel-tag dashboard-view-invoices"
                  onClick={() => setActivePage('Invoices')}
                >
                  View invoices →
                </button>
              </div>

              {invoiceLoading ? (
                <div className="company-table-state">Loading invoice information...</div>
              ) : invoiceError ? (
                <div className="company-table-state">Unable to load invoice information: {invoiceError}</div>
              ) : !invoiceData ? (
                <div className="company-table-state">No invoice information available.</div>
              ) : (
                <>
                  <div className="dashboard-invoice-stats">
                    <div className="company-overview-stat">
                      <span>Pending invoices</span>
                      <strong>{invoiceData.total_pending_invoices ?? 0}</strong>
                      <small>Awaiting payment</small>
                    </div>
                    <div className="company-overview-stat">
                      <span>Pending amount</span>
                      <strong>{formatCurrency(invoiceData.total_pending_amount)}</strong>
                      <small>Total outstanding value</small>
                    </div>
                    <div className="company-overview-stat">
                      <span>Overdue invoices</span>
                      <strong>{invoiceData.overdue_invoice_count ?? 0}</strong>
                      <small>{formatCurrency(invoiceData.total_overdue_amount)} overdue</small>
                    </div>
                  </div>

                  <div className="dashboard-overdue-heading">
                    <strong>Overdue invoice details</strong>
                    <span className="panel-tag">{(invoiceData.overdue_invoice_details || []).length} records</span>
                  </div>
                  {(invoiceData.overdue_invoice_details || []).length ? (
                    <div className="records-table-wrapper">
                      <table className="records-table dashboard-invoice-table">
                        <thead>
                          <tr>
                            <th>Invoice</th>
                            <th>Customer</th>
                            <th>Amount</th>
                            <th>Due date</th>
                            <th>Days overdue</th>
                          </tr>
                        </thead>
                        <tbody>
                          {invoiceData.overdue_invoice_details.map((invoice) => (
                            <tr key={invoice.invoice_number}>
                              <td>{invoice.invoice_number}</td>
                              <td>{invoice.customer_name}</td>
                              <td>{formatCurrency(invoice.amount)}</td>
                              <td>{invoice.due_date}</td>
                              <td>{invoice.days_overdue} days</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="company-table-state">No overdue invoices recorded.</div>
                  )}
                </>
              )}
            </div>

            <div className="dashboard-footer">
              Company observations come from confirmed uploaded financial reports. Invoice figures are shown separately from report metrics.
            </div>
          </section>
        )}

        {/* INVOICES */}
        {activePage === 'Invoices' && (
          <InvoicesPage
            invoiceData={invoiceData}
            invoiceLoading={invoiceLoading}
            invoiceError={invoiceError}
            formatCurrency={formatCurrency}
          />
        )}

        {/* UNIFIED DOCUMENT INTELLIGENCE */}
        {activePage === 'Document Intelligence' && (
          <DocumentsPage />
        )}

        {/* AI ASSISTANT */}
        {activePage === 'AI Assistant' && <VoiceAssistant />}

        {/* OTHER PAGES */}
        {![
          'Dashboard',
          'AI Assistant',
          'Document Intelligence',
          'Invoices',
        ].includes(activePage) && (
            <section className="placeholder-screen">
              <span className="eyebrow">FINAI WORKSPACE</span>
              <h1>{activePage}</h1>
              <p>
                This section will be built and connected to your backend next.
              </p>
            </section>
          )}
      </main>
    </div>
  )
}

export default App
