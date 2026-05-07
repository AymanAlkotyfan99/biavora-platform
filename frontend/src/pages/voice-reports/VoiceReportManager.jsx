import { useState, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'react-toastify'
import { useSearchParams } from 'react-router-dom'
import { 
  Mic, 
  Upload, 
  Trash2, 
  Database,
  Clock,
  BarChart3,
  CheckCircle,
  XCircle,
  Loader,
  Code,
  MessageSquare
} from 'lucide-react'

import { voiceReportsAPI, subscriptionAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import AnimatedPage from '../../components/AnimatedPage'
import Card from '../../components/Card'
import Button from '../../components/Button'
import Modal from '../../components/Modal'
import SubscriptionPlansPanel from '../../components/subscription/SubscriptionPlansPanel'
import { fadeIn, slideInBottom } from '../../animations/variants'
import {
  isReportCompleted,
  isReportFailed,
  getReportStatusBadgeClass,
  formatReportStatus,
} from '../../utils/reportStatus'

function VoiceReportManager() {
  const { user, workspace } = useAuthStore()
  const [searchParams] = useSearchParams()
  const selectedReportIdParam = searchParams.get('reportId')
  const [currentReport, setCurrentReport] = useState(null)
  const [reports, setReports] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [selectedFile, setSelectedFile] = useState(null)
  const [inputMode, setInputMode] = useState('voice')
  const [textInput, setTextInput] = useState('')
  const [isSubmittingText, setIsSubmittingText] = useState(false)
  const [processingPhase, setProcessingPhase] = useState('') // 'transcribing' | 'classifying' | 'generating' | 'executing' | 'rendering'
  const [showSubscriptionModal, setShowSubscriptionModal] = useState(false)
  const [showUsageModal, setShowUsageModal] = useState(false)
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageError, setUsageError] = useState('')
  const [usageData, setUsageData] = useState(null)

  const workspaceId = useMemo(() => {
    if (workspace?.id) return workspace.id
    if (user?.workspace?.id) return user.workspace.id
    if (Array.isArray(workspace) && workspace.length > 0) return workspace[0]?.id || null
    return null
  }, [workspace, user])

  const extractApiErrorMessage = (error, fallback = 'Processing failed') => {
    const payload = error?.response?.data
    if (typeof payload?.error === 'string' && payload.error.trim()) return payload.error.trim()
    if (typeof payload?.message === 'string' && payload.message.trim()) return payload.message.trim()
    if (typeof payload?.detail === 'string' && payload.detail.trim()) return payload.detail.trim()
    return error?.message || fallback
  }

  useEffect(() => {
    loadReports()
  }, [])

  const loadReports = async () => {
    try {
      const response = await voiceReportsAPI.listReports()
      if (response.data.success) {
        setReports(response.data.reports || [])
      }
    } catch (error) {
      console.error('Failed to load reports:', error)
    }
  }

  const handleFileSelect = (event) => {
    const file = event.target.files[0]
    if (!file) return

    // Validate file type (MIME OR extension fallback when MIME is empty/variant).
    const normalizedType = String(file.type || '').toLowerCase()
    const validTypes = [
      'audio/wav',
      'audio/x-wav',
      'audio/wave',
      'audio/vnd.wave',
      'audio/x-pn-wav',
      'audio/mpeg',
      'audio/mp3',
      'audio/mpga',
      'audio/mp4',
      'application/mp4',
      'video/mp4',
      'audio/m4a',
      'audio/x-m4a',
      'audio/ogg',
      'application/ogg',
      'audio/opus',
      'audio/webm',
      'video/webm',
      'application/octet-stream',
      '',
    ]
    const extension = String(file.name || '')
      .toLowerCase()
      .split('.')
      .pop()
    const validExtensions = ['wav', 'mp3', 'mp4', 'm4a', 'webm', 'ogg', 'mpga']
    const extensionAllowed = validExtensions.includes(extension)
    const mimeAllowed = validTypes.includes(normalizedType)
    if (!mimeAllowed && !extensionAllowed) {
      toast.error('Please upload a valid audio file (WAV, MP3, MP4, M4A, OGG, WebM)')
      return
    }

    // Validate file size (max 50MB)
    if (file.size > 50 * 1024 * 1024) {
      toast.error('Audio file must be less than 50MB')
      return
    }

    setSelectedFile(file)
  }

  const isProcessingRequest = isUploading || isSubmittingText || isExecuting
  const jobPollIntervalMs = 1000
  const jobPollTimeoutMs = Number(import.meta.env.VITE_VOICE_JOB_TIMEOUT_MS || 600000) // 10 minutes
  const isPrimaryStepComplete = ['generating', 'executing', 'rendering'].includes(processingPhase)
  const isPrimaryStepActive = processingPhase === 'transcribing' || processingPhase === 'classifying'
  const formatConfidence = (value) => {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return '-'
    return `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%`
  }

  const pollJobStatus = async (jobId, reportId, sourceMode) => {
    const startedAt = Date.now()
    let attempts = 0
    
    toast.info(
      sourceMode === 'voice'
        ? 'Audio uploaded! Processing your request...'
        : 'Text submitted! Processing your request...'
    )

    while (Date.now() - startedAt < jobPollTimeoutMs) {
      try {
        const statusResponse = await voiceReportsAPI.getJobStatus(jobId)
        const { status, stage, progress_pct, error } = statusResponse.data

        // Update progress
        if (progress_pct > 0) {
          setProcessingPhase(stage || status)
        }

        // Job completed successfully
        if (status === 'COMPLETED') {
          toast.success('Pipeline completed! Loading results...')
          await loadReports()
          const reportResponse = await voiceReportsAPI.getReport(reportId)
          
          if (reportResponse.data.success) {
            const report = reportResponse.data.report
            setCurrentReport({
              id: report.id,
              transcription: report.transcription,
              sql: report.final_sql,
              intent: report.intent_json,
              status: report.status,
              message: report.error_message || 'Success',
              confidence: report.confidence,
              degraded: report.degraded,
              chart_type: report.chart_type,
              embed_url: report.embed_url,
              row_count: report.row_count,
            })
            toast.success(`Chart generated! ${report.row_count || 0} rows visualized`)
          }
          setSelectedFile(null)
          setTextInput('')
          setProcessingPhase(null)
          return
        }

        // Job failed
        if (status === 'FAILED') {
          const errorMessage = error?.message || 'Pipeline failed. Please try again.'
          toast.error(errorMessage)
          setCurrentReport({
            id: reportId,
            status: 'failed',
            message: errorMessage,
          })
          setSelectedFile(null)
          setTextInput('')
          setProcessingPhase(null)
          await loadReports()
          return
        }

        // Still processing, wait and retry
        await new Promise(resolve => setTimeout(resolve, jobPollIntervalMs))
        attempts++
      } catch (error) {
        console.error('Error polling job status:', error)
        attempts++
        await new Promise(resolve => setTimeout(resolve, jobPollIntervalMs))
      }
    }

    // Timeout
    const timeoutMinutes = Math.round(jobPollTimeoutMs / 60000)
    toast.error(`Request timed out after ${timeoutMinutes} minute(s). The pipeline is still running in the background.`)
    setProcessingPhase(null)
    await loadReports()
  }

  const handleSubmissionResult = async (response, sourceMode) => {
    if (!response.data.success) {
      toast.error(response.data.error || 'Request failed')
      const message = response.data.message || response.data.error || ''
      if (String(message).toLowerCase().includes('reached your limit')) {
        setShowSubscriptionModal(true)
      }
      return
    }

    const jobId = response.data.job_id
    const reportId = response.data.report_id || response.data.id
    
    if (!jobId || !reportId) {
      toast.error('Request succeeded but no job ID was returned. Please try again.')
      return
    }

    // Start polling for job status
    await pollJobStatus(jobId, reportId, sourceMode)
  }

  const handleUpload = async () => {
    if (!selectedFile) {
      toast.error('Please select an audio file first')
      return
    }

    setIsUploading(true)
    setUploadProgress(0)
    setIsExecuting(true)
    setProcessingPhase('transcribing')

    try {
      const response = await voiceReportsAPI.uploadAudio(selectedFile, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        setUploadProgress(percentCompleted)
      })
      await handleSubmissionResult(response, 'voice')
    } catch (error) {
      console.error('Processing error:', error)
      const errorMessage = extractApiErrorMessage(error, 'Processing failed')
      const errorCode = String(error.response?.data?.error_code || '').trim()
      toast.error(`Error: ${errorMessage}${errorCode ? ` (${errorCode})` : ''}`)
      if (
        error.response?.status === 403 &&
        String(error.response?.data?.message || error.response?.data?.error || '')
          .toLowerCase()
          .includes('reached your limit')
      ) {
        setShowSubscriptionModal(true)
      }
    } finally {
      setIsUploading(false)
      setIsExecuting(false)
      setUploadProgress(0)
      setProcessingPhase('')
    }
  }

  const handleTextSubmit = async () => {
    const text = textInput.trim()
    if (!text) {
      return
    }

    setIsSubmittingText(true)
    setIsExecuting(true)
    setProcessingPhase('classifying')

    try {
      const response = await voiceReportsAPI.submitTextQuery(text, workspaceId)
      await handleSubmissionResult(response, 'text')
    } catch (error) {
      console.error('Text processing error:', error)
      const errorMessage = extractApiErrorMessage(error, 'Processing failed')
      toast.error(`Error: ${errorMessage}`)
      if (
        error.response?.status === 403 &&
        String(error.response?.data?.message || error.response?.data?.error || '')
          .toLowerCase()
          .includes('reached your limit')
      ) {
        setShowSubscriptionModal(true)
      }
    } finally {
      setIsSubmittingText(false)
      setIsExecuting(false)
      setProcessingPhase('')
    }
  }
  // Manager doesn't need manual execute - auto-execute happens during upload

  const handleDeleteReport = async (reportId) => {
    if (!confirm('Are you sure you want to delete this report?')) return

    try {
      const response = await voiceReportsAPI.deleteReport(reportId)
      
      if (response.data.success) {
        toast.success('Report deleted successfully')
        
        if (currentReport?.id === reportId) {
          setCurrentReport(null)
        }
        
        loadReports()
      }
    } catch (error) {
      console.error('Delete error:', error)
      toast.error('Failed to delete report')
    }
  }

  const handleLoadReport = async (reportId) => {
    try {
      const response = await voiceReportsAPI.getReport(reportId)
      
      if (response.data.success) {
        const report = response.data.report
        setCurrentReport({
          id: report.id,
          transcription: report.transcription,
          sql: report.final_sql,
          intent: report.intent,
          status: report.status,
          embedUrl: report.embed_url,
          metabaseQuestionId: report.metabase_question_id,
          rowCount: report.row_count,
          executionTime: report.execution_time_ms,
          chartType: report.final_chart_type || report.chart_type,
          finalChartType: report.final_chart_type || report.chart_type,
          selectedChartType: report.selected_chart_type,
          metabaseDisplay: report.metabase_display,
          visualizationStatus: report.visualization_status || 'success',
          confidence: report.confidence,
          degraded: report.degraded,
        })
      }
    } catch (error) {
      console.error('Failed to load report:', error)
      toast.error('Failed to load report')
    }
  }

  useEffect(() => {
    if (!selectedReportIdParam) {
      return
    }
    const parsedReportId = Number(selectedReportIdParam)
    if (Number.isNaN(parsedReportId)) {
      return
    }
    handleLoadReport(parsedReportId)
  }, [selectedReportIdParam])

  const handleOpenUsageModal = async () => {
    if (!workspaceId) {
      toast.error('Workspace is required to check subscription usage.')
      return
    }

    setShowUsageModal(true)
    setUsageLoading(true)
    setUsageError('')

    try {
      const response = await subscriptionAPI.checkAccess(workspaceId, false)
      if (response.data?.success) {
        setUsageData({
          limit: Number(response.data.limit || 0),
          used: Number(response.data.used_requests || 0),
          remaining: Number(response.data.remaining_requests || 0),
          isSubscribed: Boolean(response.data.is_subscribed),
          planName: response.data.plan?.name || 'Free Tier',
        })
      } else {
        setUsageData(null)
        setUsageError(response.data?.message || 'Unable to load usage right now.')
      }
    } catch (error) {
      setUsageData(null)
      setUsageError(error.response?.data?.message || 'Failed to load subscription usage.')
    } finally {
      setUsageLoading(false)
    }
  }

  return (
    <AnimatedPage>
      <div className="space-y-6">
        {/* Header */}
        <motion.div variants={fadeIn}>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            🎙️ Voice-Driven BI Reports
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Ask with voice or text and get instant AI-powered visualizations. No SQL knowledge required.
          </p>
        </motion.div>

        {/* Input Mode */}
        <motion.div variants={slideInBottom}>
          <div className="inline-flex rounded-lg border border-gray-200 bg-white p-1 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <button
              type="button"
              className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                inputMode === 'voice'
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'
              }`}
              onClick={() => setInputMode('voice')}
              disabled={isProcessingRequest}
            >
              Voice
            </button>
            <button
              type="button"
              className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                inputMode === 'text'
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'
              }`}
              onClick={() => setInputMode('text')}
              disabled={isProcessingRequest}
            >
              Text
            </button>
          </div>
        </motion.div>

        {/* Input Section */}
        <motion.div variants={slideInBottom}>
          <Card>
            <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">
              {inputMode === 'voice' ? 'Upload Audio' : 'Enter Text'}
            </h2>

            <div className="space-y-4">
              {inputMode === 'voice' ? (
                <>
                  <div className="flex items-center gap-4">
                    <label className="flex-1">
                      <div className="flex items-center justify-center w-full h-32 px-4 transition bg-white border-2 border-gray-300 border-dashed rounded-lg appearance-none cursor-pointer hover:border-blue-500 focus:outline-none dark:bg-gray-800 dark:border-gray-600 dark:hover:border-blue-500">
                        <div className="flex flex-col items-center space-y-2">
                          <Upload className="w-8 h-8 text-gray-600 dark:text-gray-400" />
                          <span className="text-sm text-gray-600 dark:text-gray-400">
                            {selectedFile ? selectedFile.name : 'Click to select audio file'}
                          </span>
                          <span className="text-xs text-gray-500">
                            WAV, MP3, OGG, WebM (max 50MB)
                          </span>
                        </div>
                        <input
                          type="file"
                          className="hidden"
                          accept="audio/*"
                          onChange={handleFileSelect}
                          disabled={isUploading}
                        />
                      </div>
                    </label>
                  </div>

                  <Button
                    onClick={handleUpload}
                    disabled={!selectedFile || isUploading}
                    className="w-full"
                  >
                    {isUploading ? (
                      <>
                        <Loader className="w-5 h-5 animate-spin mr-2" />
                        Processing Audio...
                      </>
                    ) : (
                      <>
                        <Upload className="w-5 h-5 mr-2" />
                        Upload and Process
                      </>
                    )}
                  </Button>
                </>
              ) : (
                <>
                  <textarea
                    className="w-full min-h-32 rounded-lg border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                    placeholder="Type your business question..."
                    value={textInput}
                    onChange={(event) => setTextInput(event.target.value)}
                    disabled={isSubmittingText}
                  />
                  <Button
                    onClick={handleTextSubmit}
                    disabled={!textInput.trim() || isSubmittingText}
                    className="w-full"
                  >
                    {isSubmittingText ? (
                      <>
                        <Loader className="w-5 h-5 animate-spin mr-2" />
                        Processing Text...
                      </>
                    ) : (
                      <>
                        <MessageSquare className="w-5 h-5 mr-2" />
                        Send
                      </>
                    )}
                  </Button>
                </>
              )}

              {inputMode === 'voice' && isUploading && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600 dark:text-gray-400">Uploading...</span>
                    <span className="text-gray-900 dark:text-white font-medium">{uploadProgress}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                    <div
                      className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {processingPhase && (
                <div className="space-y-3 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border-2 border-blue-200 dark:border-blue-800">
                  <div className="flex items-center gap-3">
                    <Loader className="w-5 h-5 text-blue-600 animate-spin" />
                    <span className="font-semibold text-blue-900 dark:text-blue-100">
                      {inputMode === 'voice' ? 'Processing Your Audio...' : 'Processing Your Text...'}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      isPrimaryStepActive
                        ? 'bg-blue-600 text-white shadow-md'
                        : isPrimaryStepComplete
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      {inputMode === 'voice' ? <Mic className="w-4 h-4" /> : <MessageSquare className="w-4 h-4" />}
                      <span className="text-xs font-medium">{inputMode === 'voice' ? 'Transcribing' : 'Classifying'}</span>
                    </div>

                    <div className="text-gray-400">-&gt;</div>

                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'generating'
                        ? 'bg-blue-600 text-white shadow-md'
                        : processingPhase === 'executing' || processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <Code className="w-4 h-4" />
                      <span className="text-xs font-medium">Generating</span>
                    </div>

                    <div className="text-gray-400">-&gt;</div>

                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'executing'
                        ? 'bg-blue-600 text-white shadow-md'
                        : processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <Database className="w-4 h-4" />
                      <span className="text-xs font-medium">Executing</span>
                    </div>

                    <div className="text-gray-400">-&gt;</div>

                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'rendering'
                        ? 'bg-blue-600 text-white shadow-md'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <BarChart3 className="w-4 h-4" />
                      <span className="text-xs font-medium">Rendering</span>
                    </div>
                  </div>
                </div>
              )}

              <Button
                variant="outline"
                className="w-full"
                onClick={handleOpenUsageModal}
              >
                Manage Subscription
              </Button>
            </div>
          </Card>
        </motion.div>

        {/* Current Report */}
        {currentReport && (
          <motion.div variants={slideInBottom}>
            <Card>
              <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white flex items-center gap-2">
                <BarChart3 className="w-6 h-6 text-blue-600" />
                Your Generated Chart
              </h2>

              {/* Results */}
              {isReportCompleted(currentReport.status) && (
                <>
                  {/* Metrics */}
                  <div className="grid grid-cols-1 gap-4 mb-6 md:grid-cols-4">
                    <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-green-600 dark:text-green-400 mb-1">
                        <Database className="w-4 h-4" />
                        <span className="text-sm font-medium">Rows</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white">
                        {currentReport.rowCount?.toLocaleString() || 0}
                      </p>
                    </div>

                    <div className="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-purple-600 dark:text-purple-400 mb-1">
                        <Clock className="w-4 h-4" />
                        <span className="text-sm font-medium">Time</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white">
                        {currentReport.executionTime}ms
                      </p>
                    </div>

                    <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-blue-600 dark:text-blue-400 mb-1">
                        <BarChart3 className="w-4 h-4" />
                        <span className="text-sm font-medium">Chart Type</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white capitalize">
                        {currentReport.finalChartType || currentReport.chartType}
                      </p>
                    </div>

                    <div className="p-4 bg-amber-50 dark:bg-amber-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300 mb-1">
                        <CheckCircle className="w-4 h-4" />
                        <span className="text-sm font-medium">Confidence</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white">
                        {formatConfidence(currentReport.confidence)}
                      </p>
                      {currentReport.degraded && (
                        <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                          Degraded
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Embedded Visualization */}
                  {(currentReport.visualizationStatus === 'partial_success' ||
                    (currentReport.finalChartType && currentReport.metabaseDisplay && currentReport.finalChartType !== currentReport.metabaseDisplay)) && (
                    <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg text-sm text-yellow-800 dark:text-yellow-300">
                      Visualization warning: chart metadata and rendered display are out of sync.
                    </div>
                  )}
                  {currentReport.embedUrl && (
                    <div className="mb-4">
                      <div className="border-2 border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden shadow-lg">
                        <iframe
                          key={`${currentReport.metabaseQuestionId || currentReport.id}-${currentReport.finalChartType || currentReport.chartType}-${currentReport.embedUrl}-${currentReport.updatedAt || ''}`}
                          src={currentReport.embedUrl}
                          width="100%"
                          height="600"
                          frameBorder="0"
                          className="bg-white"
                          title="Data Visualization"
                        />
                      </div>
                    </div>
                  )}

                  {/* Success Message */}
                  <div className="flex items-center gap-3 p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
                    <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-green-900 dark:text-green-100">
                        ✅ Chart Generated Successfully
                      </p>
                      <p className="text-sm text-green-700 dark:text-green-300">
                        Your data has been analyzed and visualized. The chart is now available in your dashboard.
                      </p>
                    </div>
                  </div>
                </>
              )}

              {/* Failed State */}
              {isReportFailed(currentReport.status) && (
                <div className="flex items-center gap-3 p-4 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                  <XCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0" />
                  <div>
                    <p className="font-medium text-red-900 dark:text-red-100">
                      ❌ Chart Generation Failed
                    </p>
                    <p className="text-sm text-red-700 dark:text-red-300">
                      There was an error processing your request. Please try again.
                    </p>
                  </div>
                </div>
              )}
            </Card>
          </motion.div>
        )}

        {/* Reports History */}
        <motion.div variants={slideInBottom}>
          <Card>
            <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">
              Your Reports
            </h2>

            {reports.length === 0 ? (
              <div className="text-center py-12">
                <Mic className="w-16 h-16 mx-auto text-gray-400 mb-4" />
                <p className="text-gray-500 dark:text-gray-400">
                  No reports yet. Submit voice or text input to get started!
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {reports.map((report) => (
                  <div
                    key={report.id}
                    className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors cursor-pointer"
                    onClick={() => handleLoadReport(report.id)}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-medium text-gray-900 dark:text-white">
                          Report #{report.id}
                        </h3>
                        <span className={`
                          px-2 py-1 text-xs rounded-full font-medium
                          ${getReportStatusBadgeClass(report.status)}
                        `}>
                          {isReportCompleted(report.status) && <CheckCircle className="w-3 h-3 inline mr-1" />}
                          {isReportFailed(report.status) && <XCircle className="w-3 h-3 inline mr-1" />}
                          {formatReportStatus(report.status)}
                        </span>
                      </div>
                      {report.row_count && (
                        <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                          <Database className="w-3 h-3 inline mr-1" />
                          {report.row_count.toLocaleString()} rows • 
                          <BarChart3 className="w-3 h-3 inline ml-2 mr-1" />
                          {report.chart_type} chart
                        </p>
                      )}
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteReport(report.id)
                      }}
                      className="ml-4 p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    >
                      <Trash2 className="w-5 h-5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </motion.div>

        <Modal
          isOpen={showUsageModal}
          onClose={() => setShowUsageModal(false)}
          title="Subscription Usage"
          size="sm"
        >
          <div className="space-y-4">
            {usageLoading ? (
              <p className="text-sm text-slate-600">Loading usage...</p>
            ) : usageError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {usageError}
              </div>
            ) : usageData ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Plan</p>
                  <p className="mt-1 text-sm font-medium text-slate-900">{usageData.planName}</p>
                </div>
                <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
                  <p className="text-sm font-medium text-blue-900">Usage</p>
                  <p className="mt-1 text-sm text-blue-800">
                    {usageData.used} / {usageData.limit} requests used
                  </p>
                  <p className="mt-1 text-sm text-blue-800">{usageData.remaining} remaining</p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-600">No usage details available.</p>
            )}

            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setShowUsageModal(false)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>

        <Modal
          isOpen={showSubscriptionModal}
          onClose={() => setShowSubscriptionModal(false)}
          title="Upgrade Subscription"
          size="xl"
        >
          <SubscriptionPlansPanel
            workspaceId={workspaceId}
            title="Unlock More Voice Requests"
            onSubscribed={() => setShowSubscriptionModal(false)}
          />
        </Modal>
      </div>
    </AnimatedPage>
  )
}

export default VoiceReportManager
