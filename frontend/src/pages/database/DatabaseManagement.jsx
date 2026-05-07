import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Upload, Database as DatabaseIcon, FileText, Trash2, 
  AlertCircle, CheckCircle, Loader, Info, Table, 
  RefreshCw, X, AlertTriangle
} from 'lucide-react'
import { databaseAPI } from '../../api/endpoints'
import { toast } from 'react-toastify'
import { fadeIn, cardVariants, scaleIn } from '../../animations/variants'
import { Card, Button, Modal, LoadingSpinner } from '../../components'

function DatabaseManagement() {
  const [database, setDatabase] = useState(null)
  const [previewData, setPreviewData] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showReplaceModal, setShowReplaceModal] = useState(false)
  const [fileToUpload, setFileToUpload] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)

  useEffect(() => {
    loadDatabaseInfo()
  }, [])

  const loadDatabaseInfo = async () => {
    try {
      setIsLoading(true)
      const response = await databaseAPI.getDatabaseInfo()
      if (response.data.success) {
        setDatabase(response.data.data)
        // Load preview if database is completed
        if (response.data.data.etl_status === 'completed') {
          loadPreview()
        }
      }
    } catch (error) {
      if (error.response?.status === 404) {
        // No database found - this is normal for new users
        setDatabase(null)
      } else if (error.response?.status === 503) {
        console.error('Backend service unavailable:', error)
        // Don't show error for initial load - user hasn't uploaded yet
        setDatabase(null)
      } else {
        console.error('Error loading database:', error)
        // Only show error if it's not a connection issue on first load
        if (error.response) {
          toast.error('Failed to load database information')
        }
      }
    } finally {
      setIsLoading(false)
    }
  }

  const loadPreview = async () => {
    try {
      setIsLoadingPreview(true)
      const response = await databaseAPI.getDatabasePreview()
      if (response.data.success) {
        setPreviewData(response.data.data)
      }
    } catch (error) {
      console.error('Error loading preview:', error)
      // Don't show error toast for preview loading failures
    } finally {
      setIsLoadingPreview(false)
    }
  }

  const handleFileSelect = (file) => {
    if (!file) return
    
    // Validate file type
    const allowedTypes = [
      'text/csv',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'text/plain'
    ]
    
    if (!allowedTypes.includes(file.type) && !file.name.match(/\.(csv|xlsx|xls)$/i)) {
      toast.error('Please upload a valid CSV or Excel file')
      return
    }

    // Check if database exists (replace mode)
    if (database) {
      setFileToUpload(file)
      setShowReplaceModal(true)
    } else {
      uploadFile(file)
    }
  }

  const uploadFile = async (file) => {
    try {
      setIsUploading(true)
      setUploadProgress(0)

      const response = await databaseAPI.uploadDatabase(file, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        setUploadProgress(percentCompleted)
      })

      if (response.data.success) {
        toast.success(response.data.message)
        setDatabase(response.data.data)
        setShowReplaceModal(false)
        setFileToUpload(null)
        
        // Poll for ETL completion
        pollETLStatus()
      }
    } catch (error) {
      console.error('Upload error:', error)
      
      // Defensive error message handling
      let errorMessage = 'Upload failed'
      
      if (error.response) {
        // Server responded with error
        const status = error.response.status
        const data = error.response.data
        
        if (status === 503) {
          errorMessage = 'ETL service is unavailable. Please ensure the ETL system is running and try again.'
        } else if (status === 504) {
          errorMessage = 'Upload timeout. Please try again with a smaller file.'
        } else if (status === 502) {
          errorMessage = 'ETL service error. Please check the ETL system logs.'
        } else if (status === 404) {
          errorMessage = 'Database upload endpoint not found. Please contact support.'
        } else if (data && typeof data === 'object' && data.message) {
          errorMessage = data.message
        } else if (typeof data === 'string') {
          errorMessage = data
        }
      } else if (error.request) {
        // Request made but no response
        errorMessage = 'Cannot connect to backend. Please ensure the server is running.'
      } else {
        // Something else happened
        errorMessage = error.message || 'An unexpected error occurred'
      }
      
      toast.error(errorMessage)
    } finally {
      setIsUploading(false)
      setUploadProgress(0)
    }
  }

  const pollETLStatus = () => {
    const interval = setInterval(async () => {
      try {
        const response = await databaseAPI.getDatabaseInfo()
        if (response.data.success) {
          const db = response.data.data
          setDatabase(db)
          
          if (db.etl_status === 'completed') {
            clearInterval(interval)
            toast.success('Database processing completed!')
            loadPreview()
          } else if (db.etl_status === 'failed') {
            clearInterval(interval)
            toast.error('Database processing failed')
          }
        }
      } catch (error) {
        clearInterval(interval)
      }
    }, 3000) // Poll every 3 seconds

    // Stop polling after 5 minutes
    setTimeout(() => clearInterval(interval), 300000)
  }

  const handleDelete = async () => {
    try {
      const response = await databaseAPI.deleteDatabase()
      if (response.data.success) {
        toast.success('Database deleted successfully')
        setDatabase(null)
        setPreviewData(null)
        setShowDeleteModal(false)
      }
    } catch (error) {
      console.error('Delete error:', error)
      
      // Defensive error handling
      let errorMessage = 'Delete failed'
      if (error.response?.data?.message) {
        errorMessage = error.response.data.message
      } else if (error.response?.status === 404) {
        errorMessage = 'Database not found'
        // Still reset UI since it doesn't exist
        setDatabase(null)
        setPreviewData(null)
        setShowDeleteModal(false)
      } else if (!error.response) {
        errorMessage = 'Cannot connect to backend'
      }
      
      toast.error(errorMessage)
    }
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    
    const files = e.dataTransfer.files
    if (files.length > 0) {
      handleFileSelect(files[0])
    }
  }

  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <LoadingSpinner size="large" />
      </div>
    )
  }

  return (
    <motion.div
      variants={fadeIn}
      initial="hidden"
      animate="visible"
      className="max-w-7xl mx-auto space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Database Management</h1>
          <p className="mt-2 text-gray-600">Upload and manage your data source</p>
        </div>
        {database && (
          <Button
            variant="danger"
            icon={Trash2}
            onClick={() => setShowDeleteModal(true)}
          >
            Delete Database
          </Button>
        )}
      </div>

      {/* Upload Area or Database Info */}
      {!database ? (
        <motion.div variants={cardVariants} initial="hidden" animate="visible">
          <UploadArea
            isDragging={isDragging}
            isUploading={isUploading}
            uploadProgress={uploadProgress}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onFileSelect={handleFileSelect}
          />
        </motion.div>
      ) : (
        <>
          <motion.div variants={cardVariants} initial="hidden" animate="visible">
            <DatabaseInfo database={database} />
          </motion.div>
          
          {database.etl_status === 'completed' && previewData && (
            <>
              <motion.div variants={cardVariants} initial="hidden" animate="visible" transition={{ delay: 0.1 }}>
                <SchemaPreview schema={previewData} />
              </motion.div>
              <motion.div variants={cardVariants} initial="hidden" animate="visible" transition={{ delay: 0.2 }}>
                <DataPreview previewData={previewData} isLoading={isLoadingPreview} />
              </motion.div>
            </>
          )}
          
          {database.etl_status === 'processing' && (
            <motion.div variants={cardVariants} initial="hidden" animate="visible">
              <ProcessingCard />
            </motion.div>
          )}
          
          {database.etl_status === 'failed' && (
            <motion.div variants={cardVariants} initial="hidden" animate="visible">
              <ErrorCard message={database.etl_message} />
            </motion.div>
          )}
        </>
      )}

      {/* Replace Database Modal */}
      <AnimatePresence>
        {showReplaceModal && (
          <Modal
            isOpen={showReplaceModal}
            onClose={() => {
              setShowReplaceModal(false)
              setFileToUpload(null)
            }}
            title="Replace Database"
          >
            <div className="space-y-4">
              <div className="flex items-start space-x-3 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                <AlertTriangle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-yellow-900">Warning: This action cannot be undone</p>
                  <p className="text-sm text-yellow-700 mt-1">
                    This will permanently delete your current database and all data stored in ClickHouse.
                    The new file will be uploaded and processed automatically.
                  </p>
                </div>
              </div>
              
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  <strong>Current file:</strong> {database?.filename}
                </p>
                <p className="text-sm text-gray-600">
                  <strong>New file:</strong> {fileToUpload?.name}
                </p>
              </div>

              <div className="flex space-x-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowReplaceModal(false)
                    setFileToUpload(null)
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={() => uploadFile(fileToUpload)}
                  disabled={isUploading}
                  className="flex-1"
                >
                  {isUploading ? 'Replacing...' : 'Replace Database'}
                </Button>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {showDeleteModal && (
          <Modal
            isOpen={showDeleteModal}
            onClose={() => setShowDeleteModal(false)}
            title="Delete Database"
          >
            <div className="space-y-4">
              <div className="flex items-start space-x-3 p-4 bg-red-50 border border-red-200 rounded-lg">
                <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-red-900">Warning: This action cannot be undone</p>
                  <p className="text-sm text-red-700 mt-1">
                    This will permanently delete your database and all associated data from ClickHouse.
                  </p>
                </div>
              </div>

              <div className="flex space-x-3">
                <Button
                  variant="secondary"
                  onClick={() => setShowDeleteModal(false)}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={handleDelete}
                  className="flex-1"
                >
                  Delete Permanently
                </Button>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// Upload Area Component
function UploadArea({ isDragging, isUploading, uploadProgress, onDragOver, onDragLeave, onDrop, onFileSelect }) {
  const fileInputRef = useState(null)[0]

  return (
    <Card className="p-8">
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={`
            relative border-2 border-dashed rounded-xl p-12 text-center transition-all duration-300
            ${isDragging 
              ? 'border-primary-500 bg-primary-50' 
              : 'border-gray-300 hover:border-primary-400 hover:bg-gray-50'
            }
            ${isUploading ? 'pointer-events-none opacity-60' : ''}
          `}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => onFileSelect(e.target.files[0])}
            className="hidden"
            id="file-upload"
          />

          {isUploading ? (
            <motion.div
              variants={scaleIn}
              initial="hidden"
              animate="visible"
              className="space-y-4"
            >
              <Loader className="w-16 h-16 mx-auto text-primary-600 animate-spin" />
              <div>
                <p className="text-lg font-semibold text-gray-900">Uploading...</p>
                <p className="text-sm text-gray-600 mt-1">{uploadProgress}% complete</p>
              </div>
              <div className="w-full max-w-md mx-auto bg-gray-200 rounded-full h-2">
                <motion.div
                  className="bg-primary-600 h-2 rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${uploadProgress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </motion.div>
          ) : (
            <motion.div variants={scaleIn} className="space-y-4">
              <motion.div
                animate={isDragging ? { scale: 1.1 } : { scale: 1 }}
                transition={{ duration: 0.2 }}
              >
                <Upload className="w-16 h-16 mx-auto text-gray-400" />
              </motion.div>
              
              <div>
                <label htmlFor="file-upload" className="cursor-pointer">
                  <span className="text-lg font-semibold text-primary-600 hover:text-primary-700">
                    Click to upload
                  </span>
                  <span className="text-gray-600"> or drag and drop</span>
                </label>
                <p className="text-sm text-gray-500 mt-2">
                  CSV, XLSX, or XLS files
                </p>
              </div>

              <Button
                variant="primary"
                icon={Upload}
                onClick={() => document.getElementById('file-upload').click()}
                className="mt-4"
              >
                Select File
              </Button>
            </motion.div>
          )}
        </div>
      </Card>
  )
}

// Database Info Component
function DatabaseInfo({ database }) {
  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString()
  }

  const statusConfig = {
    pending: { color: 'gray', icon: AlertCircle, text: 'Pending' },
    processing: { color: 'blue', icon: Loader, text: 'Processing' },
    completed: { color: 'green', icon: CheckCircle, text: 'Completed' },
    failed: { color: 'red', icon: AlertCircle, text: 'Failed' }
  }

  const status = statusConfig[database.etl_status] || statusConfig.pending
  const StatusIcon = status.icon

  return (
    <Card>
        <div className="p-6">
          <div className="flex items-center space-x-3 mb-6">
            <div className="p-3 bg-primary-100 rounded-lg">
              <DatabaseIcon className="w-6 h-6 text-primary-600" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">Database Information</h2>
              <p className="text-sm text-gray-600">Overview of your uploaded database</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <InfoItem
              icon={FileText}
              label="Filename"
              value={database.filename}
            />
            <InfoItem
              icon={Info}
              label="File Size"
              value={database.file_size_formatted || formatFileSize(database.file_size)}
            />
            <InfoItem
              icon={Table}
              label="Rows"
              value={database.row_count?.toLocaleString() || '-'}
            />
            <InfoItem
              icon={Table}
              label="Columns"
              value={database.column_count?.toLocaleString() || '-'}
            />
            <InfoItem
              icon={CheckCircle}
              label="Upload Date"
              value={formatDate(database.upload_date)}
            />
            <InfoItem
              icon={StatusIcon}
              label="Status"
              value={
                <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-${status.color}-100 text-${status.color}-700`}>
                  <StatusIcon className={`w-4 h-4 mr-1 ${database.etl_status === 'processing' ? 'animate-spin' : ''}`} />
                  {status.text}
                </span>
              }
            />
          </div>
        </div>
      </Card>
  )
}

// Info Item Component
function InfoItem({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start space-x-3">
      <div className="p-2 bg-gray-100 rounded-lg">
        <Icon className="w-5 h-5 text-gray-600" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-500">{label}</p>
        <p className="text-base font-semibold text-gray-900 truncate mt-1">{value}</p>
      </div>
    </div>
  )
}

// Schema Preview Component
function SchemaPreview({ schema }) {
  return (
    <Card>
        <div className="p-6">
          <h3 className="text-lg font-bold text-gray-900 mb-4">Schema Information</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Column Name
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Data Type
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {schema.columns.map((column, idx) => (
                  <motion.tr
                    key={idx}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                  >
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {column}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      <code className="px-2 py-1 bg-gray-100 rounded text-xs">
                        {schema.column_types?.[column] || 'String'}
                      </code>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>
  )
}

// Data Preview Component
function DataPreview({ previewData, isLoading }) {
  if (isLoading) {
    return (
      <Card>
        <div className="p-6">
          <div className="flex items-center justify-center py-12">
            <LoadingSpinner />
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-900">Data Preview</h3>
          <span className="text-sm text-gray-600">First 5 rows</span>
        </div>
          
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {previewData.columns.map((column, idx) => (
                    <th
                      key={idx}
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {previewData.rows.map((row, rowIdx) => (
                  <motion.tr
                    key={rowIdx}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: rowIdx * 0.1 }}
                  >
                    {previewData.columns.map((column, colIdx) => (
                      <td
                        key={colIdx}
                        className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap"
                      >
                        {row[column] !== null && row[column] !== undefined 
                          ? String(row[column]) 
                          : '-'}
                      </td>
                    ))}
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 text-sm text-gray-600 text-center">
          Showing 5 of {previewData.total_rows?.toLocaleString()} rows
        </div>
      </div>
    </Card>
  )
}

// Processing Card Component
function ProcessingCard() {
  return (
    <Card>
        <div className="p-6 text-center">
          <Loader className="w-12 h-12 mx-auto text-blue-600 animate-spin mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Processing Your Data</h3>
          <p className="text-gray-600">
            Your database is being processed through the ETL pipeline. This may take a few moments.
          </p>
        </div>
      </Card>
  )
}

// Error Card Component
function ErrorCard({ message }) {
  return (
    <Card>
        <div className="p-6">
          <div className="flex items-start space-x-3 p-4 bg-red-50 border border-red-200 rounded-lg">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="font-semibold text-red-900 mb-1">Processing Failed</h4>
              <p className="text-sm text-red-700">
                {message || 'An error occurred while processing your database.'}
              </p>
            </div>
          </div>
        </div>
      </Card>
  )
}

export default DatabaseManagement

