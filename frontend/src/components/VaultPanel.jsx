import { useState, useEffect, useRef } from 'react'
import { X, Upload, Trash2, Database, FileText, Image } from 'lucide-react'
import { getDocuments, uploadDocument, deleteDocument } from '../api'

export default function VaultPanel({ project, onClose }) {
  const [docs, setDocs]         = useState([])
  const [scope, setScope]       = useState('project')
  const [uploading, setUploading] = useState(false)
  const fileInputRef             = useRef(null)

  useEffect(() => {
    loadDocs()
  }, [project?.id, scope])

  const loadDocs = async () => {
    try {
      const res = await getDocuments(
        scope === 'project' ? project?.id : null,
        scope
      )
      setDocs(res.data)
    } catch (e) {
      console.error('Failed to load docs', e)
    }
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await uploadDocument(file, project?.id, scope)
      await loadDocs()
    } catch (err) {
      console.error('Upload failed', err)
      alert('Upload failed. Check that the backend is running.')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleDelete = async (docId) => {
    if (!confirm('Remove this document from the vault?')) return
    try {
      await deleteDocument(docId)
      await loadDocs()
    } catch (e) {
      console.error('Delete failed', e)
    }
  }

  const getIcon = (fileType) => {
    if (['png', 'jpg', 'jpeg'].includes(fileType)) return <Image size={14} />
    return <FileText size={14} />
  }

  const getIconBg = (fileType) => {
    if (fileType === 'pdf')  return 'bg-red-50 text-red-600'
    if (fileType === 'docx') return 'bg-blue-50 text-blue-600'
    if (['png', 'jpg'].includes(fileType)) return 'bg-green-50 text-green-600'
    return 'bg-gray-100 text-gray-600'
  }

  return (
    <div className="w-56 flex-shrink-0 border-l border-gray-100 bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="px-3 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-800">
          <Database size={14} /> Document Vault
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <X size={15} />
        </button>
      </div>

      {/* Scope tabs */}
      <div className="px-2 py-2 border-b border-gray-100 flex gap-1">
        <button
          onClick={() => setScope('project')}
          className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
            scope === 'project'
              ? 'bg-white text-gray-900 font-medium border border-gray-200'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          {project?.name || 'Project'}
        </button>
        <button
          onClick={() => setScope('global')}
          className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
            scope === 'global'
              ? 'bg-white text-gray-900 font-medium border border-gray-200'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          Global
        </button>
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1">
        {docs.map(doc => (
          <div
            key={doc.id}
            className="flex items-center gap-2 p-2 rounded-lg border border-gray-200 bg-white group"
          >
            <div className={`w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 ${getIconBg(doc.file_type)}`}>
              {getIcon(doc.file_type)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-800 truncate">{doc.name}</p>
              <p className="text-xs text-gray-400">{doc.chunk_count} chunks</p>
            </div>
            <button
              onClick={() => handleDelete(doc.id)}
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all flex-shrink-0"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        {docs.length === 0 && (
          <div className="text-center py-6">
            <Database size={24} className="text-gray-300 mx-auto mb-2" />
            <p className="text-xs text-gray-400">No documents yet</p>
            <p className="text-xs text-gray-400">Upload to get started</p>
          </div>
        )}
      </div>

      {/* Upload area */}
      <div className="p-2 border-t border-gray-100">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
          className="hidden"
          onChange={handleUpload}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="w-full py-2.5 border border-dashed border-gray-300 rounded-lg text-xs text-gray-500 hover:bg-white hover:border-gray-400 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
        >
          <Upload size={13} />
          {uploading ? 'Uploading...' : 'Upload to vault'}
        </button>
        <p className="text-xs text-gray-400 text-center mt-1">
          PDF, DOCX, TXT, PNG · Used in all chats
        </p>
      </div>
    </div>
  )
}
