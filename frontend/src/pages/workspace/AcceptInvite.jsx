import { useEffect, useState } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { CheckCircle, XCircle, UserPlus, Loader2 } from 'lucide-react'
import { workspaceAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import { toast } from 'react-toastify'
import Button from '../../components/Button'
import AnimatedPage from '../../components/AnimatedPage'

function AcceptInvite() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { isAuthenticated } = useAuthStore()
  const token = searchParams.get('token')
  
  const [status, setStatus] = useState('loading') // loading, success, error, signup_required
  const [message, setMessage] = useState('')
  const [workspaceInfo, setWorkspaceInfo] = useState(null)
  const [invitedEmail, setInvitedEmail] = useState('')
  const [invitedRole, setInvitedRole] = useState('')

  useEffect(() => {
    if (token) {
      acceptInvitation()
    } else {
      setStatus('error')
      setMessage('No invitation token provided')
    }
  }, [token])

  const acceptInvitation = async () => {
    try {
      setStatus('loading')
      console.log('Attempting to accept invitation with token:', token)
      const response = await workspaceAPI.acceptInvitation(token)
      console.log('Accept invitation response:', response.data)
      
      // === CASE A: Existing user - redirect to LOGIN ===
      if (response.data.success && response.data.need_login) {
        setStatus('success')
        setMessage(response.data.message)
        setWorkspaceInfo(response.data.workspace)
        toast.success('Invitation accepted! Please log in.')
        
        // Redirect to login page with joined flag
        setTimeout(() => {
          navigate('/login?joined=true')
        }, 1500)
      }
      // === CASE B: New user - redirect to REGISTRATION ===
      else if (response.data.success && response.data.need_register) {
        // New user - needs to sign up first
        const email = response.data.email
        const role = response.data.role
        const invitation_token = response.data.invitation_token
        const workspaceName = response.data.workspace?.name || 'workspace'
        
        console.log('Redirecting to signup:', { email, role, invitation_token })
        
        // Store data in state
        setInvitedEmail(email)
        setInvitedRole(role)
        setWorkspaceInfo(response.data.workspace)
        
        // Redirect to signup with invitation token
        navigate(`/signup?email=${encodeURIComponent(email)}&role=${role}&token=${invitation_token}&workspace=${encodeURIComponent(workspaceName)}`)
      }
      // === CASE C: Legacy response handling ===
      else if (response.data.success) {
        // Already accepted or other success case
        setStatus('success')
        setMessage(response.data.message || 'Invitation accepted!')
        setWorkspaceInfo(response.data.workspace)
        toast.success('Success!')
        
        // Redirect to login
        setTimeout(() => {
          navigate('/login?joined=true')
        }, 1500)
      }
    } catch (error) {
      console.error('Accept invitation error:', error)
      
      // Check if it's a network or server error
      if (!error.response) {
        setStatus('error')
        setMessage('Network error. Please check your connection.')
        toast.error('Network error')
        return
      }
      
      // Handle different error status codes
      const statusCode = error.response?.status
      const errorData = error.response?.data
      
      if (statusCode === 400 && errorData?.message) {
        // Invalid token or validation error
        setStatus('error')
        const errorMsg = errorData.message
        
        // Set specific error messages
        if (errorMsg.includes('expired')) {
          setMessage('Invitation link has expired. Please ask the workspace manager to send you a new invitation.')
        } else if (errorMsg.includes('Invalid invitation link')) {
          setMessage('Invalid invitation link. Please check your email and use the latest invitation link.')
        } else if (errorMsg.includes('already been used')) {
          setMessage('This invitation has already been accepted. Please log in to access the workspace.')
        } else {
          setMessage(errorMsg)
        }
        
        toast.error(errorMsg)
      } else {
        // Generic error
        setStatus('error')
        const errorMsg = errorData?.message || 'Failed to accept invitation. The link may be invalid or expired.'
        setMessage(errorMsg)
        toast.error(errorMsg)
      }
    }
  }

  if (!token) {
    return (
      <div className="card text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-4">
          <XCircle className="w-8 h-8 text-red-600" />
        </div>
        <h2 className="text-2xl font-bold text-gray-900 mb-3">Invalid Invitation</h2>
        <p className="text-gray-600 mb-6">No invitation token was provided.</p>
        <Link to="/">
          <Button fullWidth>Back to Home</Button>
        </Link>
      </div>
    )
  }

  const handleSignupRedirect = () => {
    if (invitedEmail && invitedRole && token && workspaceInfo) {
      navigate(`/signup?email=${encodeURIComponent(invitedEmail)}&role=${invitedRole}&token=${token}&workspace=${encodeURIComponent(workspaceInfo.name)}`)
    } else {
      navigate('/signup')
    }
  }

  return (
    <AnimatedPage>
    <div className="card text-center">
      {status === 'loading' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-primary-100 rounded-full mb-4">
            <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Processing Invitation</h2>
          <p className="text-gray-600">Please wait while we process your workspace invitation...</p>
        </>
      )}

      {status === 'success' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
            <CheckCircle className="w-8 h-8 text-green-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Invitation Accepted!</h2>
          <p className="text-gray-600 mb-2">{message}</p>
          {workspaceInfo && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6 mt-4">
              <p className="text-sm text-green-800">
                <strong>Workspace:</strong> {workspaceInfo.name}
              </p>
            </div>
          )}
          {isAuthenticated ? (
            <>
              <p className="text-sm text-gray-500 mb-6">
                Redirecting to dashboard...
              </p>
              <Link to="/dashboard/members">
                <Button fullWidth>Go to Dashboard</Button>
              </Link>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-500 mb-6">
                Redirecting to login page...
              </p>
              <Link to="/login?workspace_joined=true">
                <Button fullWidth>Go to Login</Button>
              </Link>
            </>
          )}
        </>
      )}

      {status === 'signup_required' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full mb-4">
            <UserPlus className="w-8 h-8 text-blue-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Sign Up Required</h2>
          <p className="text-gray-600 mb-4">{message}</p>
          {workspaceInfo && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
              <p className="text-sm text-blue-800 mb-2">
                <strong>Invited to:</strong> {workspaceInfo.name}
              </p>
              {invitedEmail && (
                <p className="text-sm text-blue-800 mb-1">
                  <strong>Email:</strong> {invitedEmail}
                </p>
              )}
              {invitedRole && (
                <p className="text-sm text-blue-800">
                  <strong>Role:</strong> {invitedRole.charAt(0).toUpperCase() + invitedRole.slice(1)}
                </p>
              )}
            </div>
          )}
          <p className="text-sm text-gray-600 mb-6">
            Please create an account to accept this invitation and join the workspace.
          </p>
          <div className="space-y-3">
            <Button fullWidth onClick={handleSignupRedirect}>
              <UserPlus className="w-5 h-5" />
              <span>Create Account</span>
            </Button>
            <Link to="/login">
              <Button variant="secondary" fullWidth>
                Already have an account? Login
              </Button>
            </Link>
          </div>
        </>
      )}

      {status === 'error' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-4">
            <XCircle className="w-8 h-8 text-red-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Invitation Failed</h2>
          <p className="text-gray-600 mb-6">{message}</p>
          <div className="space-y-3">
            <Link to="/login">
              <Button fullWidth>Go to Login</Button>
            </Link>
            <Link to="/">
              <Button variant="secondary" fullWidth>
                Back to Home
              </Button>
            </Link>
          </div>
        </>
      )}
    </div>
    </AnimatedPage>
  )
}

export default AcceptInvite

