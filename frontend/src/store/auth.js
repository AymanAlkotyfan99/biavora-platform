import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authAPI, userAPI } from '../api/endpoints'
import { toast } from 'react-toastify'

export const useAuthStore = create(
  persist(
    (set, get) => ({
      // State
      user: null,
      workspace: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,

      // Actions
      
      // Login
      login: async (email, password) => {
        try {
          set({ isLoading: true })
          const response = await authAPI.login({ email, password })
          
          const { access, refresh, user, workspace } = response.data
          
          // Store tokens
          localStorage.setItem('access_token', access)
          localStorage.setItem('refresh_token', refresh)
          
          set({
            user,
            workspace,
            accessToken: access,
            refreshToken: refresh,
            isAuthenticated: true,
            isLoading: false,
          })
          
          toast.success(`Welcome back, ${user.name}!`)
          return { success: true, user }
        } catch (error) {
          set({ isLoading: false })
          const message = error.response?.data?.message || 'Login failed'
          toast.error(message)
          return { success: false, error: message }
        }
      },

      // Signup
      signup: async (data) => {
        try {
          set({ isLoading: true })
          const response = await authAPI.signup(data)
          set({ isLoading: false })
          toast.success('Account created! Check your email to verify.')
          return { success: true, data: response.data }
        } catch (error) {
          set({ isLoading: false })
          const message = error.response?.data?.message || 'Signup failed'
          toast.error(message)
          return { success: false, error: message }
        }
      },

      // Logout
      logout: async () => {
        try {
          const refreshToken = get().refreshToken || localStorage.getItem('refresh_token')
          if (refreshToken) {
            await authAPI.logout(refreshToken)
          }
        } catch (error) {
          console.error('Logout error:', error)
        } finally {
          // Clear state and storage
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          
          set({
            user: null,
            workspace: null,
            accessToken: null,
            refreshToken: null,
            isAuthenticated: false,
          })
          
          toast.success('Logged out successfully')
        }
      },

      // Load user profile
      loadUser: async () => {
        try {
          const token = localStorage.getItem('access_token')
          if (!token) {
            set({ isAuthenticated: false })
            return { success: false }
          }

          const response = await userAPI.getProfile()
          const { user, workspace } = response.data
          
          set({
            user,
            workspace: workspace || user?.workspace || null,
            isAuthenticated: true,
          })
          
          return { success: true, user }
        } catch (error) {
          console.error('Load user error:', error)
          get().logout()
          return { success: false }
        }
      },
      
      // Refresh user profile (useful after role changes)
      refreshUser: async () => {
        const result = await get().loadUser()
        if (result?.success) {
          toast.success('Profile updated')
        }
        return result
      },

      // Update user in store
      updateUser: (userData) => {
        set({ user: { ...get().user, ...userData } })
      },

      // Check if user has role
      hasRole: (roles) => {
        const { user } = get()
        if (!user) return false
        if (Array.isArray(roles)) {
          return roles.includes(user.role)
        }
        return user.role === roles
      },

      // Initialize auth from storage
      initialize: () => {
        const token = localStorage.getItem('access_token')
        const refresh = localStorage.getItem('refresh_token')
        
        if (token && refresh) {
          set({
            accessToken: token,
            refreshToken: refresh,
          })
          get().loadUser()
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        workspace: state.workspace,
      }),
    }
  )
)

// Initialize auth on load
if (typeof window !== 'undefined') {
  useAuthStore.getState().initialize()
}

