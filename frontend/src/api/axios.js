import axios from 'axios'
import { useAuthStore } from '../store/auth'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

// Create axios instance
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // withCredentials removed - not needed for JWT authentication
})

// Request interceptor - Add JWT token to requests
apiClient.interceptors.request.use(
  (config) => {
    if (typeof FormData !== 'undefined' && config?.data instanceof FormData && config?.headers) {
      // Let the browser set multipart boundaries automatically.
      delete config.headers['Content-Type']
      delete config.headers['content-type']
    }
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// List of public endpoints that don't need authentication
const PUBLIC_ENDPOINTS = [
  '/auth/signup/',
  '/auth/login/',
  '/auth/verify-email/',
  '/auth/forgot-password/request/',
  '/auth/forgot-password/verify/',
  '/auth/forgot-password/reset/',
  '/workspace/accept-invite/',
]

// Response interceptor - Handle token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Check if this is a public endpoint
    const isPublicEndpoint = PUBLIC_ENDPOINTS.some(endpoint => 
      originalRequest.url?.includes(endpoint)
    )

    // If error is 401 and we haven't retried yet and it's not a public endpoint
    if (error.response?.status === 401 && !originalRequest._retry && !isPublicEndpoint) {
      originalRequest._retry = true

      try {
        const refreshToken = localStorage.getItem('refresh_token')
        
        if (refreshToken) {
          // Try to refresh the token
          const response = await axios.post(`${API_BASE_URL}/auth/token/refresh/`, {
            refresh: refreshToken
          })

          const { access } = response.data
          localStorage.setItem('access_token', access)

          // Retry the original request with new token
          originalRequest.headers.Authorization = `Bearer ${access}`
          return apiClient(originalRequest)
        }
      } catch (refreshError) {
        // Refresh failed, logout user
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        window.location.href = '/login'
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

export default apiClient

