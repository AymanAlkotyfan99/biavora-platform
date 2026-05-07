import { useState, useEffect } from 'react'
import { useAuthStore } from '../../store/auth'
import { workspaceAPI } from '../../api/endpoints'
import { UserPlus, Mail, Shield, Send, CheckCircle, Clock, UserCheck, Trash2, Users } from 'lucide-react'
import { toast } from 'react-toastify'
import Card from '../../components/Card'
import Input from '../../components/Input'
import Select from '../../components/Select'
import Button from '../../components/Button'
import Badge from '../../components/Badge'
import LoadingSpinner from '../../components/LoadingSpinner'
import AnimatedPage from '../../components/AnimatedPage'
import { Link } from 'react-router-dom'

function InviteMember() {
  const { hasRole } = useAuthStore()
  
  const [formData, setFormData] = useState({
    email: '',
    role: 'analyst',
  })
  
  const [isLoading, setIsLoading] = useState(false)
  const [errors, setErrors] = useState({})
  const [inviteSent, setInviteSent] = useState(false)
  
  // Members lists
  const [membersLoading, setMembersLoading] = useState(true)
  const [acceptedMembers, setAcceptedMembers] = useState([])
  const [pendingMembers, setPendingMembers] = useState([])
  const [invitedMembers, setInvitedMembers] = useState([])
  
  useEffect(() => {
    loadMembers()
  }, [])

  // Only managers can access this page
  if (!hasRole('manager')) {
    return (
      <div className="max-w-2xl mx-auto">
        <Card>
          <div className="text-center py-8">
            <UserPlus className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600">
              Only workspace owners (managers) can invite members.
            </p>
          </div>
        </Card>
      </div>
    )
  }

  const loadMembers = async () => {
    try {
      setMembersLoading(true)
      const response = await workspaceAPI.getMembers()
      setAcceptedMembers(response.data.accepted_members || [])
      setPendingMembers(response.data.pending_members || [])
      setInvitedMembers(response.data.invited_members || [])
    } catch (error) {
      console.error('Failed to load members:', error)
    } finally {
      setMembersLoading(false)
    }
  }

  const handleRemoveInvitation = async (email) => {
    if (!confirm(`Remove pending invitation for ${email}?`)) {
      return
    }
    
    try {
      await workspaceAPI.removeInvitation(email)
      toast.success('Invitation removed successfully')
      loadMembers()
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to remove invitation'
      toast.error(errorMsg)
    }
  }

  const roleOptions = [
    { value: 'analyst', label: 'Analyst - Analyze data and create reports' },
    { value: 'executive', label: 'Executive - View reports and dashboards' },
  ]

  const validateForm = () => {
    const newErrors = {}
    
    if (!formData.email.trim()) {
      newErrors.email = 'Email is required'
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Email is invalid'
    }
    
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleChange = (e) => {
    setFormData({
      ...formData,
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
      await workspaceAPI.inviteMember(formData)
      
      toast.success('Invitation sent successfully!')
      setInviteSent(true)
      
      // Reload members list
      loadMembers()
      
      // Reset form after 3 seconds
      setTimeout(() => {
        setFormData({ email: '', role: 'analyst' })
        setInviteSent(false)
      }, 3000)
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to send invitation'
      toast.error(errorMsg)
    } finally {
      setIsLoading(false)
    }
  }

  const handleInviteAnother = () => {
    setFormData({ email: '', role: 'analyst' })
    setInviteSent(false)
  }

  const getStatusBadge = (status) => {
    const variants = {
      active: 'success',
      pending_acceptance: 'warning',
      pending_registration: 'info',
      suspended: 'danger',
    }
    const labels = {
      active: 'Active',
      pending_acceptance: 'Pending Acceptance',
      pending_registration: 'Pending Registration',
      suspended: 'Suspended',
    }
    return <Badge variant={variants[status] || 'default'}>{labels[status] || status}</Badge>
  }

  return (
    <AnimatedPage>
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Invite Team Member</h1>
          <p className="text-gray-600 mt-1">Send an invitation to join your workspace</p>
        </div>
      </div>

      {!inviteSent ? (
        <Card>
          <div className="flex items-center space-x-3 pb-6 border-b mb-6">
            <div className="w-12 h-12 bg-primary-100 rounded-lg flex items-center justify-center">
              <UserPlus className="w-6 h-6 text-primary-600" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                Invitation Details
              </h3>
              <p className="text-sm text-gray-600">
                Enter the email address and role for the new member
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <Input
              label="Email Address"
              icon={Mail}
              name="email"
              type="email"
              required
              value={formData.email}
              onChange={handleChange}
              error={errors.email}
              placeholder="colleague@example.com"
            />

            <Select
              label="Role"
              name="role"
              value={formData.role}
              onChange={handleChange}
              options={roleOptions}
            />

            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-start space-x-3">
                <Shield className="w-5 h-5 text-blue-600 mt-0.5" />
                <div className="text-sm text-blue-800">
                  <p className="font-medium mb-1">About Roles:</p>
                  <ul className="space-y-1 text-xs">
                    <li>
                      <strong>Analyst:</strong> Can analyze data, create reports, and collaborate on dashboards
                    </li>
                    <li>
                      <strong>Executive:</strong> Can view reports and dashboards with read-only access
                    </li>
                  </ul>
                  <p className="mt-2 text-xs">
                    Note: You can change a member's role later from the Members page.
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <div className="flex items-start space-x-3">
                <Mail className="w-5 h-5 text-yellow-600 mt-0.5" />
                <div className="text-sm text-yellow-800">
                  <p className="font-medium mb-1">Invitation Process:</p>
                  <ol className="list-decimal list-inside space-y-1 text-xs">
                    <li>An invitation email will be sent to the provided address</li>
                    <li>The invitation link expires in 48 hours</li>
                    <li>If they don't have an account, they'll need to sign up first</li>
                    <li>They'll automatically join your workspace upon acceptance</li>
                  </ol>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t">
              <Link to="/dashboard/members">
                <Button variant="secondary">
                  View Members
                </Button>
              </Link>
              <Button
                type="submit"
                loading={isLoading}
              >
                {isLoading ? (
                  'Sending...'
                ) : (
                  <>
                    <Send className="w-5 h-5" />
                    <span>Send Invitation</span>
                  </>
                )}
              </Button>
            </div>
          </form>
        </Card>
      ) : (
        <Card>
          <div className="text-center py-8">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
              <CheckCircle className="w-8 h-8 text-green-600" />
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-3">
              Invitation Sent!
            </h2>
            <p className="text-gray-600 mb-6">
              An invitation has been sent to <strong>{formData.email}</strong>
            </p>
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6">
              <p className="text-sm text-green-800">
                The recipient will receive an email with instructions to join your workspace. 
                The invitation link will expire in 48 hours.
              </p>
            </div>
            <div className="flex items-center justify-center space-x-3">
              <Button
                onClick={handleInviteAnother}
              >
                <UserPlus className="w-5 h-5" />
                <span>Invite Another Member</span>
              </Button>
              <Link to="/dashboard/members">
                <Button variant="secondary">
                  View All Members
                </Button>
              </Link>
            </div>
          </div>
        </Card>
      )}

      {/* Members List Section */}
      <Card>
        <div className="flex items-center justify-between pb-4 border-b mb-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">
              Workspace Members & Invitations
            </h3>
            <p className="text-sm text-gray-600 mt-1">
              Overview of all members and pending invitations
            </p>
          </div>
        </div>

        {membersLoading ? (
          <div className="flex items-center justify-center py-8">
            <LoadingSpinner />
          </div>
        ) : (
          <div className="space-y-6">
            {/* Pending Registration - Not yet signed up */}
            {invitedMembers.length > 0 && (
              <div>
                <div className="flex items-center space-x-2 mb-3">
                  <Clock className="w-5 h-5 text-blue-500" />
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                    Pending Registration ({invitedMembers.length})
                  </h4>
                </div>
                <div className="bg-blue-50 rounded-lg overflow-hidden">
                  <table className="w-full">
                    <thead className="bg-blue-100">
                      <tr>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-blue-900">Email</th>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-blue-900">Role</th>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-blue-900">Status</th>
                        <th className="text-right py-2 px-4 text-xs font-semibold text-blue-900">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {invitedMembers.map((member, index) => (
                        <tr key={index} className="border-t border-blue-200">
                          <td className="py-3 px-4 text-sm text-gray-900">{member.email}</td>
                          <td className="py-3 px-4 text-sm text-gray-700 capitalize">{member.role}</td>
                          <td className="py-3 px-4">{getStatusBadge(member.status)}</td>
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => handleRemoveInvitation(member.email)}
                              className="text-red-600 hover:text-red-800 text-sm font-medium"
                              title="Remove invitation"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Pending Acceptance - Signed up but not accepted */}
            {pendingMembers.length > 0 && (
              <div>
                <div className="flex items-center space-x-2 mb-3">
                  <Mail className="w-5 h-5 text-yellow-500" />
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                    Pending Acceptance ({pendingMembers.length})
                  </h4>
                </div>
                <div className="bg-yellow-50 rounded-lg overflow-hidden">
                  <table className="w-full">
                    <thead className="bg-yellow-100">
                      <tr>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-yellow-900">Name</th>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-yellow-900">Email</th>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-yellow-900">Role</th>
                        <th className="text-left py-2 px-4 text-xs font-semibold text-yellow-900">Status</th>
                        <th className="text-right py-2 px-4 text-xs font-semibold text-yellow-900">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pendingMembers.map((member, index) => (
                        <tr key={index} className="border-t border-yellow-200">
                          <td className="py-3 px-4 text-sm text-gray-900">{member.name}</td>
                          <td className="py-3 px-4 text-sm text-gray-900">{member.email}</td>
                          <td className="py-3 px-4 text-sm text-gray-700 capitalize">{member.role}</td>
                          <td className="py-3 px-4">{getStatusBadge(member.status)}</td>
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => handleRemoveInvitation(member.email)}
                              className="text-red-600 hover:text-red-800 text-sm font-medium"
                              title="Remove invitation"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Active Members - Preview */}
            {acceptedMembers.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <UserCheck className="w-5 h-5 text-green-500" />
                    <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Active Members ({acceptedMembers.length})
                    </h4>
                  </div>
                  <Link to="/dashboard/members">
                    <Button variant="secondary" size="sm">
                      View All Members
                    </Button>
                  </Link>
                </div>
                <div className="bg-green-50 rounded-lg p-4">
                  <p className="text-sm text-green-800">
                    You have {acceptedMembers.length} active member{acceptedMembers.length !== 1 ? 's' : ''} in your workspace.{' '}
                    <Link to="/dashboard/members" className="font-medium underline hover:text-green-900">
                      View full member list
                    </Link>
                  </p>
                </div>
              </div>
            )}

            {invitedMembers.length === 0 && pendingMembers.length === 0 && acceptedMembers.length === 0 && (
              <div className="text-center py-8 text-gray-500">
                <Users className="w-12 h-12 mx-auto mb-3 text-gray-400" />
                <p>No members or invitations yet</p>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
    </AnimatedPage>
  )
}

export default InviteMember

