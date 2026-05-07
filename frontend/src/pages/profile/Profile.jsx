import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  Calendar,
  KeyRound,
  Lock,
  Loader2,
  Mail,
  MapPin,
  Save,
  Shield,
  User,
} from 'lucide-react'
import { toast } from 'react-toastify'

import { userAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import { AnimatedPage, Badge, Button, Card, Input, Modal } from '../../components'
import {
  badgeScale,
  glowHover,
  headerTitle,
  listItem,
  scaleFade,
  staggerContainer,
  staggerFast,
} from '../../animations/uiVariants'

function Profile() {
  const navigate = useNavigate()
  const { user, updateUser, logout } = useAuthStore()

  const [profile, setProfile] = useState({
    first_name: '',
    last_name: '',
    date_of_birth: '',
    home_address: '',
    email: '',
  })
  const [originalProfile, setOriginalProfile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isChangingPassword, setIsChangingPassword] = useState(false)
  const [isDeactivating, setIsDeactivating] = useState(false)
  const [showDeactivateModal, setShowDeactivateModal] = useState(false)
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false)
  const [errors, setErrors] = useState({})
  const [passwordErrors, setPasswordErrors] = useState({})
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: '',
    confirm_new_password: '',
  })

  useEffect(() => {
    loadProfile()
  }, [])

  const loadProfile = async () => {
    try {
      const response = await userAPI.getProfile()
      const userData = response.data?.user || {}
      const nextProfile = {
        first_name: userData.first_name || '',
        last_name: userData.last_name || '',
        date_of_birth: userData.date_of_birth || '',
        home_address: userData.home_address || '',
        email: userData.email || '',
      }
      setProfile(nextProfile)
      setOriginalProfile(nextProfile)
      updateUser(userData)
    } catch (error) {
      toast.error('Failed to load profile')
    }
  }

  const validateProfile = () => {
    const nextErrors = {}
    if (!profile.first_name.trim()) {
      nextErrors.first_name = 'First name is required'
    }
    if (!profile.last_name.trim()) {
      nextErrors.last_name = 'Last name is required'
    }
    setErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const handleProfileChange = (event) => {
    const { name, value } = event.target
    setProfile((previous) => ({
      ...previous,
      [name]: value,
    }))
    if (errors[name]) {
      setErrors((previous) => ({
        ...previous,
        [name]: null,
      }))
    }
  }

  const handleProfileSubmit = async (event) => {
    event.preventDefault()
    if (!validateProfile()) {
      return
    }
    if (!originalProfile) {
      return
    }

    const payload = {}
    ;['first_name', 'last_name', 'date_of_birth', 'home_address'].forEach((field) => {
      const currentValue = profile[field] ?? ''
      const originalValue = originalProfile[field] ?? ''
      if (currentValue !== originalValue) {
        payload[field] = currentValue
      }
    })

    if (Object.keys(payload).length === 0) {
      toast.info('No changes to save')
      return
    }

    try {
      setIsLoading(true)
      const response = await userAPI.updateProfile(payload)
      const updatedUser = response.data?.user || {}
      const refreshedProfile = {
        first_name: updatedUser.first_name || '',
        last_name: updatedUser.last_name || '',
        date_of_birth: updatedUser.date_of_birth || '',
        home_address: updatedUser.home_address || '',
        email: updatedUser.email || profile.email,
      }
      setProfile(refreshedProfile)
      setOriginalProfile(refreshedProfile)
      updateUser(updatedUser)
      toast.success('Profile updated successfully!')
    } catch (error) {
      const message = error.response?.data?.message || 'Failed to update profile'
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  const handlePasswordInputChange = (event) => {
    const { name, value } = event.target
    setPasswordForm((previous) => ({
      ...previous,
      [name]: value,
    }))
    if (passwordErrors[name]) {
      setPasswordErrors((previous) => ({
        ...previous,
        [name]: null,
      }))
    }
  }

  const validatePasswordForm = () => {
    const nextErrors = {}
    if (!passwordForm.current_password) {
      nextErrors.current_password = 'Current password is required'
    }
    if (!passwordForm.new_password) {
      nextErrors.new_password = 'New password is required'
    }
    if (passwordForm.new_password !== passwordForm.confirm_new_password) {
      nextErrors.confirm_new_password = 'New password and confirmation do not match'
    }
    setPasswordErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const handleChangePassword = async (event) => {
    event.preventDefault()
    if (!validatePasswordForm()) {
      return
    }

    try {
      setIsChangingPassword(true)
      await userAPI.changePassword(passwordForm)
      toast.success('Password changed successfully!')
      setPasswordForm({
        current_password: '',
        new_password: '',
        confirm_new_password: '',
      })
      setShowChangePasswordModal(false)
    } catch (error) {
      const backendErrors = error.response?.data?.errors || {}
      const message = error.response?.data?.message

      if (backendErrors.current_password?.[0]) {
        setPasswordErrors({ current_password: backendErrors.current_password[0] })
      } else if (backendErrors.confirm_new_password?.[0]) {
        setPasswordErrors({ confirm_new_password: backendErrors.confirm_new_password[0] })
      } else if (backendErrors.new_password?.[0]) {
        setPasswordErrors({ new_password: backendErrors.new_password[0] })
      } else {
        toast.error(message || 'Failed to change password')
      }
    } finally {
      setIsChangingPassword(false)
    }
  }

  const handleDeactivate = async () => {
    try {
      setIsDeactivating(true)
      const refreshToken = localStorage.getItem('refresh_token')
      await userAPI.deactivateAccount(refreshToken)
      toast.success('Account deactivated successfully')
      setShowDeactivateModal(false)
      await logout()
      navigate('/login')
    } catch (error) {
      const message = error.response?.data?.message || 'Failed to deactivate account'
      toast.error(message)
    } finally {
      setIsDeactivating(false)
    }
  }

  return (
    <AnimatedPage className="max-w-4xl mx-auto space-y-6">
      <motion.div variants={headerTitle} initial="hidden" animate="visible" className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Profile Settings</h1>
          <p className="text-gray-600 mt-1">Manage your account information</p>
        </div>
      </motion.div>

      <motion.div variants={scaleFade} initial="hidden" animate="visible">
        <Card title="Profile Information">
          <form onSubmit={handleProfileSubmit}>
            <motion.div variants={staggerFast} initial="hidden" animate="visible" className="space-y-6">
              <motion.div variants={listItem} className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Input
                  label="First Name"
                  icon={User}
                  name="first_name"
                  type="text"
                  required
                  value={profile.first_name}
                  onChange={handleProfileChange}
                  error={errors.first_name}
                  placeholder="First name"
                />
                <Input
                  label="Last Name"
                  icon={User}
                  name="last_name"
                  type="text"
                  required
                  value={profile.last_name}
                  onChange={handleProfileChange}
                  error={errors.last_name}
                  placeholder="Last name"
                />
              </motion.div>

              <motion.div variants={listItem} className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Input
                  label="Date of Birth"
                  icon={Calendar}
                  name="date_of_birth"
                  type="date"
                  value={profile.date_of_birth || ''}
                  onChange={handleProfileChange}
                  error={errors.date_of_birth}
                />
                <Input
                  label="Email Address"
                  icon={Mail}
                  name="email"
                  type="email"
                  value={profile.email}
                  disabled
                  className="bg-gray-100 cursor-not-allowed"
                />
              </motion.div>

              <motion.div variants={listItem}>
                <label htmlFor="home_address" className="block text-sm font-medium text-gray-700 mb-2">
                  Home Address
                </label>
                <div className="relative">
                  <MapPin className="absolute left-3 top-3 w-5 h-5 text-gray-400" />
                  <textarea
                    id="home_address"
                    name="home_address"
                    rows={3}
                    value={profile.home_address}
                    onChange={handleProfileChange}
                    className="input pl-10 resize-none"
                    placeholder="Enter your home address"
                  />
                </div>
              </motion.div>

              <motion.div variants={listItem} className="flex items-center justify-between pt-4 border-t">
                <Button type="button" variant="secondary" onClick={loadProfile}>
                  Reset Changes
                </Button>
                <motion.div whileHover="hover" whileTap="tap" variants={glowHover}>
                  <Button type="submit" loading={isLoading}>
                    {isLoading ? (
                      <>
                        <Loader2 className="w-5 h-5 animate-spin" />
                        <span>Saving...</span>
                      </>
                    ) : (
                      <>
                        <Save className="w-5 h-5" />
                        <span>Save Changes</span>
                      </>
                    )}
                  </Button>
                </motion.div>
              </motion.div>
            </motion.div>
          </form>
        </Card>
      </motion.div>

      <motion.div variants={scaleFade} initial="hidden" animate="visible" transition={{ delay: 0.1 }}>
        <Card title="Security">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
            <div className="flex items-start space-x-4">
              <KeyRound className="w-6 h-6 text-blue-600 mt-1" />
              <div className="flex-1">
                <h4 className="text-lg font-semibold text-blue-900 mb-2">Change Password</h4>
                <p className="text-sm text-blue-800 mb-4">
                  Update your account password securely by confirming your current password first.
                </p>
                <Button onClick={() => setShowChangePasswordModal(true)}>
                  <KeyRound className="w-5 h-5" />
                  <span>Change Password</span>
                </Button>
              </div>
            </div>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={scaleFade} initial="hidden" animate="visible" transition={{ delay: 0.2 }}>
        <Card title="Account Information">
          <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-4">
            <motion.div variants={listItem} className="flex items-center justify-between py-3 border-b">
              <div className="flex items-center space-x-3">
                <Shield className="w-5 h-5 text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-900">Role</p>
                  <p className="text-xs text-gray-500">Your account type</p>
                </div>
              </div>
              <motion.div variants={badgeScale} initial="hidden" animate="visible">
                <Badge variant={user?.role === 'manager' ? 'info' : 'success'}>{user?.role}</Badge>
              </motion.div>
            </motion.div>

            <motion.div variants={listItem} className="flex items-center justify-between py-3 border-b">
              <div className="flex items-center space-x-3">
                <Mail className="w-5 h-5 text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-900">Email Status</p>
                  <p className="text-xs text-gray-500">Verification status</p>
                </div>
              </div>
              <motion.div variants={badgeScale} initial="hidden" animate="visible">
                <Badge variant={user?.is_verified ? 'success' : 'warning'}>
                  {user?.is_verified ? 'Verified' : 'Pending'}
                </Badge>
              </motion.div>
            </motion.div>

            <motion.div variants={listItem} className="flex items-center justify-between py-3">
              <div className="flex items-center space-x-3">
                <User className="w-5 h-5 text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-900">Account Status</p>
                  <p className="text-xs text-gray-500">Active or suspended</p>
                </div>
              </div>
              <motion.div variants={badgeScale} initial="hidden" animate="visible">
                <Badge variant={user?.is_active ? 'success' : 'danger'}>
                  {user?.is_active ? 'Active' : 'Suspended'}
                </Badge>
              </motion.div>
            </motion.div>
          </motion.div>
        </Card>
      </motion.div>

      <motion.div variants={scaleFade} initial="hidden" animate="visible" transition={{ delay: 0.3 }}>
        <Card title="Danger Zone">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6">
            <div className="flex items-start space-x-4">
              <AlertTriangle className="w-6 h-6 text-red-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h4 className="text-lg font-semibold text-red-900 mb-2">Deactivate Account</h4>
                <p className="text-sm text-red-800 mb-4">
                  Once you deactivate your account, you will lose access to all workspaces and your data.
                </p>
                <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
                  <Button variant="danger" onClick={() => setShowDeactivateModal(true)}>
                    <AlertTriangle className="w-5 h-5" />
                    <span>Deactivate Account</span>
                  </Button>
                </motion.div>
              </div>
            </div>
          </div>
        </Card>
      </motion.div>

      <Modal
        isOpen={showChangePasswordModal}
        onClose={() => setShowChangePasswordModal(false)}
        title="Change Password"
      >
        <form onSubmit={handleChangePassword} className="space-y-4">
          <Input
            label="Current Password"
            icon={Lock}
            name="current_password"
            type="password"
            value={passwordForm.current_password}
            onChange={handlePasswordInputChange}
            error={passwordErrors.current_password}
            required
          />
          <Input
            label="New Password"
            icon={Lock}
            name="new_password"
            type="password"
            value={passwordForm.new_password}
            onChange={handlePasswordInputChange}
            error={passwordErrors.new_password}
            required
          />
          <Input
            label="Confirm New Password"
            icon={Lock}
            name="confirm_new_password"
            type="password"
            value={passwordForm.confirm_new_password}
            onChange={handlePasswordInputChange}
            error={passwordErrors.confirm_new_password}
            required
          />
          <div className="flex justify-end space-x-3 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setShowChangePasswordModal(false)}
              disabled={isChangingPassword}
            >
              Cancel
            </Button>
            <Button type="submit" loading={isChangingPassword}>
              {isChangingPassword ? 'Updating...' : 'Update Password'}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={showDeactivateModal}
        onClose={() => setShowDeactivateModal(false)}
        title="Deactivate Account"
      >
        <div className="space-y-4">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5" />
              <div className="text-sm text-red-800">
                <p className="font-medium mb-2">Are you absolutely sure?</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>You will lose access to all workspaces</li>
                  <li>Your dashboards and reports will be inaccessible</li>
                  <li>You will need to contact support to reactivate</li>
                </ul>
              </div>
            </div>
          </div>

          <p className="text-gray-600">
            This action will deactivate your account. To continue, click the button below.
          </p>

          <div className="flex items-center justify-end space-x-3 pt-4">
            <Button variant="secondary" onClick={() => setShowDeactivateModal(false)} disabled={isDeactivating}>
              Cancel
            </Button>
            <Button variant="danger" onClick={handleDeactivate} loading={isDeactivating}>
              {isDeactivating ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Deactivating...</span>
                </>
              ) : (
                'Yes, Deactivate Account'
              )}
            </Button>
          </div>
        </div>
      </Modal>
    </AnimatedPage>
  )
}

export default Profile
