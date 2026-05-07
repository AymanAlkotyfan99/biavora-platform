import { useEffect, useState } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { CheckCircle, XCircle, Mail, Loader2 } from 'lucide-react'
import { authAPI } from '../../api/endpoints'
import { toast } from 'react-toastify'
import Button from '../../components/Button'

function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')
  const sent = searchParams.get('sent')
  const invited = searchParams.get('invited')
  
  const [status, setStatus] = useState('loading') // loading, success, error
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (token) {
      verifyEmail()
    } else if (!sent) {
      setStatus('error')
      setMessage('No verification token provided')
    }
  }, [token])

  const verifyEmail = async () => {
    try {
      setStatus('loading')
      const response = await authAPI.verifyEmail(token)
      setStatus('success')
      setMessage(response.data.message || 'Your account has been verified successfully!')
      toast.success('Email verified successfully!')
      
      // Redirect to login after 3 seconds
      setTimeout(() => {
        navigate('/login')
      }, 3000)
    } catch (error) {
      setStatus('error')
      const errorMsg = error.response?.data?.message || 'Verification failed. The link may be invalid or expired.'
      setMessage(errorMsg)
      toast.error(errorMsg)
    }
  }

  // If just redirected after signup
  if (sent && !token) {
    return (
      <div className="card text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full mb-4">
          <Mail className="w-8 h-8 text-blue-600" />
        </div>
        <h2 className="text-2xl font-bold text-gray-900 mb-3">
          {invited ? 'Account Created!' : 'Check Your Email'}
        </h2>
        {invited ? (
          <>
            <p className="text-gray-600 mb-4">
              Your account has been created successfully and you've been added to the workspace!
            </p>
            <p className="text-gray-600 mb-6">
              We've sent a verification link to your email address. 
              Please verify your email to access all features.
            </p>
          </>
        ) : (
          <p className="text-gray-600 mb-6">
            We've sent a verification link to your email address. 
            Please check your inbox and click the link to verify your account.
          </p>
        )}
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
          <p className="text-sm text-yellow-800">
            <strong>Note:</strong> The verification link will expire in 24 hours.
            If you don't see the email, check your spam folder.
          </p>
        </div>
        <Link to="/login">
          <Button variant="secondary" fullWidth>
            {invited ? 'Go to Login' : 'Back to Login'}
          </Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="card text-center">
      {status === 'loading' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-primary-100 rounded-full mb-4">
            <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Verifying Your Email</h2>
          <p className="text-gray-600">Please wait while we verify your email address...</p>
        </>
      )}

      {status === 'success' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
            <CheckCircle className="w-8 h-8 text-green-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Email Verified!</h2>
          <p className="text-gray-600 mb-6">{message}</p>
          <p className="text-sm text-gray-500 mb-6">
            Redirecting to login page in 3 seconds...
          </p>
          <Link to="/login">
            <Button fullWidth>
              Go to Login
            </Button>
          </Link>
        </>
      )}

      {status === 'error' && (
        <>
          <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-4">
            <XCircle className="w-8 h-8 text-red-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Verification Failed</h2>
          <p className="text-gray-600 mb-6">{message}</p>
          <div className="space-y-3">
            <Link to="/login">
              <Button fullWidth>
                Go to Login
              </Button>
            </Link>
            <Link to="/signup">
              <Button variant="secondary" fullWidth>
                Create New Account
              </Button>
            </Link>
          </div>
        </>
      )}
    </div>
  )
}

export default VerifyEmail

