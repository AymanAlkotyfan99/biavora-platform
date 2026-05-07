import { useState, useEffect } from 'react'
import { useAuthStore } from '../../store/auth'
import { workspaceAPI } from '../../api/endpoints'
import { Settings, Save, Loader2, Building } from 'lucide-react'
import { toast } from 'react-toastify'
import Card from '../../components/Card'
import Input from '../../components/Input'
import Button from '../../components/Button'

function WorkspaceSettings() {
  const { user, hasRole } = useAuthStore()
  
  const [workspace, setWorkspace] = useState({
    name: '',
    description: '',
    company_number: '',
    company_address: '',
  })
  
  const [isLoading, setIsLoading] = useState(false)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    if (hasRole('manager')) {
      loadWorkspace()
    }
  }, [user?.role])

  // Only managers can access this page
  if (!hasRole('manager')) {
    return (
      <div className="max-w-2xl mx-auto">
        <Card>
          <div className="text-center py-8">
            <Settings className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600">
              Only workspace owners (managers) can access workspace settings.
            </p>
          </div>
        </Card>
      </div>
    )
  }

  const validateForm = () => {
    const newErrors = {}
    
    if (!workspace.name.trim()) {
      newErrors.name = 'Workspace name is required'
    }
    
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const loadWorkspace = async () => {
    try {
      const response = await workspaceAPI.getWorkspace()
      if (response.data?.workspace) {
        setWorkspace({
          name: response.data.workspace.name || '',
          description: response.data.workspace.description || '',
          company_number: response.data.workspace.company_number || '',
          company_address: response.data.workspace.company_address || '',
        })
      }
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to load workspace'
      toast.error(errorMsg)
    }
  }

  const handleChange = (e) => {
    setWorkspace({
      ...workspace,
      [e.target.name]: e.target.value,
    })
    if (errors[e.target.name]) {
      setErrors({
        ...errors,
        [e.target.name]: null,
      })
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    if (!validateForm()) {
      return
    }
    
    try {
      setIsLoading(true)
      const response = await workspaceAPI.updateWorkspace(workspace)
      
      toast.success('Workspace updated successfully!')
      
      // Update workspace info in the form
      if (response.data.workspace) {
        setWorkspace({
          name: response.data.workspace.name,
          description: response.data.workspace.description || '',
          company_number: response.data.workspace.company_number || '',
          company_address: response.data.workspace.company_address || '',
        })
      }
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to update workspace'
      toast.error(errorMsg)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Workspace Settings</h1>
          <p className="text-gray-600 mt-1">Manage your workspace configuration</p>
        </div>
      </div>

      <Card>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="flex items-center space-x-3 pb-6 border-b">
            <div className="w-12 h-12 bg-primary-100 rounded-lg flex items-center justify-center">
              <Building className="w-6 h-6 text-primary-600" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                Workspace Information
              </h3>
              <p className="text-sm text-gray-600">
                Update your workspace name and description
              </p>
            </div>
          </div>

          <Input
            label="Workspace Name"
            icon={Building}
            name="name"
            type="text"
            required
            value={workspace.name}
            onChange={handleChange}
            error={errors.name}
            placeholder="My Awesome Workspace"
          />

          <div>
            <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-2">
              Description (Optional)
            </label>
            <textarea
              id="description"
              name="description"
              rows={4}
              value={workspace.description}
              onChange={handleChange}
              className="input resize-none"
              placeholder="Describe your workspace and its purpose..."
            />
          </div>

          <Input
            label="Company Number"
            icon={Building}
            name="company_number"
            type="text"
            value={workspace.company_number}
            onChange={handleChange}
            error={errors.company_number}
            placeholder="Enter company registration number"
          />

          <div>
            <label htmlFor="company_address" className="block text-sm font-medium text-gray-700 mb-2">
              Company Address
            </label>
            <textarea
              id="company_address"
              name="company_address"
              rows={3}
              value={workspace.company_address}
              onChange={handleChange}
              className="input resize-none"
              placeholder="Enter company address..."
            />
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <Settings className="w-5 h-5 text-blue-600 mt-0.5" />
              <div className="text-sm text-blue-800">
                <p className="font-medium mb-1">Workspace Information</p>
                <p>
                  This workspace is owned by you. Only workspace owners can update 
                  these settings, invite members, and manage roles.
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end pt-4 border-t">
            <Button
              type="submit"
              loading={isLoading}
            >
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
          </div>
        </form>
      </Card>

      {/* Additional Information */}
      <Card title="Workspace Owner">
        <div className="space-y-3">
          <div className="flex items-center justify-between py-2">
            <span className="text-sm font-medium text-gray-700">Owner Name</span>
            <span className="text-sm text-gray-900">{user?.name}</span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-sm font-medium text-gray-700">Owner Email</span>
            <span className="text-sm text-gray-900">{user?.email}</span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-sm font-medium text-gray-700">Role</span>
            <span className="text-sm text-gray-900 capitalize">{user?.role}</span>
          </div>
        </div>
      </Card>
    </div>
  )
}

export default WorkspaceSettings

