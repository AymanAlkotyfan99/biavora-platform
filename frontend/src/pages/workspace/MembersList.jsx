import { useState, useEffect } from 'react'
import { useAuthStore } from '../../store/auth'
import { workspaceAPI } from '../../api/endpoints'
import { Users, Mail, Shield, AlertCircle, Trash2, UserX, UserCheck, Edit, Clock } from 'lucide-react'
import { toast } from 'react-toastify'
import Card from '../../components/Card'
import Badge from '../../components/Badge'
import Button from '../../components/Button'
import Modal from '../../components/Modal'
import Select from '../../components/Select'
import LoadingSpinner from '../../components/LoadingSpinner'
import EmptyState from '../../components/EmptyState'
import AnimatedPage from '../../components/AnimatedPage'

function MembersList() {
  const { user, hasRole } = useAuthStore()
  
  const [acceptedMembers, setAcceptedMembers] = useState([])
  const [pendingMembers, setPendingMembers] = useState([])
  const [invitedMembers, setInvitedMembers] = useState([])
  const [workspaceId, setWorkspaceId] = useState(null)
  const [workspaceName, setWorkspaceName] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [selectedMember, setSelectedMember] = useState(null)
  const [showRoleModal, setShowRoleModal] = useState(false)
  const [showRemoveModal, setShowRemoveModal] = useState(false)
  const [showSuspendModal, setShowSuspendModal] = useState(false)
  const [newRole, setNewRole] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  useEffect(() => {
    loadMembers()
  }, [])

  const loadMembers = async () => {
    try {
      setIsLoading(true)
      const response = await workspaceAPI.getMembers()
      setAcceptedMembers(response.data.accepted_members || [])
      setPendingMembers(response.data.pending_members || [])
      setInvitedMembers(response.data.invited_members || [])
      setWorkspaceId(response.data.workspace_id)
      setWorkspaceName(response.data.workspace_name || 'Workspace')
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to load members'
      // Show the actual error message from backend
      toast.error(errorMsg)
    } finally {
      setIsLoading(false)
    }
  }

  const handleRoleChange = async () => {
    if (!selectedMember || !newRole) return
    
    try {
      setActionLoading(true)
      await workspaceAPI.assignRole(selectedMember.id, newRole)
      toast.success('Role updated successfully!')
      setShowRoleModal(false)
      loadMembers()
      
      // If the changed member is the current user, refresh their profile
      if (selectedMember.id === user?.id) {
        const { loadUser } = useAuthStore.getState()
        await loadUser()
        toast.info('Your role has been updated. Some menu items may have changed.')
      }
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to update role'
      toast.error(errorMsg)
    } finally {
      setActionLoading(false)
    }
  }

  const handleSuspend = async () => {
    if (!selectedMember) return
    
    try {
      setActionLoading(true)
      
      if (selectedMember.status === 'suspended') {
        await workspaceAPI.unsuspendMember(selectedMember.id)
        toast.success('Member unsuspended successfully!')
      } else {
        await workspaceAPI.suspendMember(selectedMember.id)
        toast.success('Member suspended successfully!')
      }
      
      setShowSuspendModal(false)
      loadMembers()
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to update member status'
      toast.error(errorMsg)
    } finally {
      setActionLoading(false)
    }
  }

  const handleRemove = async () => {
    if (!selectedMember) return
    
    try {
      setActionLoading(true)
      
      // If member has no id (pending registration), remove by email
      if (!selectedMember.id) {
        await workspaceAPI.removeInvitation(selectedMember.email)
        toast.success('Invitation removed successfully!')
      } else {
        await workspaceAPI.removeMember(selectedMember.id)
        toast.success('Member removed successfully!')
      }
      
      setShowRemoveModal(false)
      loadMembers()
    } catch (error) {
      const errorMsg = error.response?.data?.message || 'Failed to remove member'
      toast.error(errorMsg)
    } finally {
      setActionLoading(false)
    }
  }

  const openRoleModal = (member) => {
    setSelectedMember(member)
    setNewRole(member.role)
    setShowRoleModal(true)
  }

  const openSuspendModal = (member) => {
    setSelectedMember(member)
    setShowSuspendModal(true)
  }

  const openRemoveModal = (member) => {
    setSelectedMember(member)
    setShowRemoveModal(true)
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

  const isManager = hasRole('manager')
  
  // Only Managers see all members (active + pending + invited)
  // Executives and Analysts see only active members
  const allMembers = isManager 
    ? [...acceptedMembers, ...pendingMembers, ...invitedMembers]
    : acceptedMembers
  const totalCount = allMembers.length

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <AnimatedPage>
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Workspace Members</h1>
          <p className="text-gray-600 mt-1">
            {workspaceName} - {totalCount} member{totalCount !== 1 ? 's' : ''} total
          </p>
        </div>
        {isManager && (
          <Button onClick={() => window.location.href = '/dashboard/invite'}>
            <Users className="w-5 h-5" />
            <span>Invite Member</span>
          </Button>
        )}
      </div>

      {totalCount === 0 ? (
        <EmptyState
          icon={Users}
          title="No members found"
          description={isManager ? "Your workspace doesn't have any members yet. Invite team members to get started." : "No active members found in this workspace."}
          action={
            isManager && (
              <Button onClick={() => window.location.href = '/dashboard/invite'}>
                Invite Member
              </Button>
            )
          }
        />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-900">
                    Member
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-900">
                    Role
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-900">
                    Status
                  </th>
                  {isManager && (
                    <th className="text-right py-3 px-4 text-sm font-semibold text-gray-900">
                      Actions
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {allMembers.map((member, index) => {
                  const isCurrentUser = member.id === user?.id
                  const canManage = isManager && !isCurrentUser && member.role !== 'manager'
                  const isPending = member.status === 'pending_registration' || member.status === 'pending_acceptance'

                  return (
                    <tr key={member.id || `pending-${index}`} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-4 px-4">
                        <div className="flex items-center space-x-3">
                          <div className="w-10 h-10 bg-primary-100 rounded-full flex items-center justify-center">
                            <span className="text-primary-600 font-semibold">
                              {member.name.charAt(0).toUpperCase()}
                            </span>
                          </div>
                          <div>
                            <p className="text-sm font-medium text-gray-900">
                              {member.name}
                              {isCurrentUser && (
                                <span className="ml-2 text-xs text-gray-500">(You)</span>
                              )}
                            </p>
                            <p className="text-xs text-gray-600 flex items-center space-x-1">
                              <Mail className="w-3 h-3" />
                              <span>{member.email}</span>
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="py-4 px-4">
                        <div className="flex items-center space-x-2">
                          <Shield className="w-4 h-4 text-gray-400" />
                          <span className="text-sm text-gray-900 capitalize">
                            {member.role}
                          </span>
                        </div>
                      </td>
                      <td className="py-4 px-4">
                        {getStatusBadge(member.status)}
                      </td>
                      {isManager && (
                        <td className="py-4 px-4">
                          <div className="flex items-center justify-end space-x-2">
                            {isPending ? (
                              // Pending invitations - only show remove
                              <button
                                onClick={() => openRemoveModal(member)}
                                className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                title="Remove Invitation"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            ) : canManage ? (
                              // Active members - show all management options
                              <>
                                <button
                                  onClick={() => openRoleModal(member)}
                                  className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                                  title="Change Role"
                                >
                                  <Edit className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => openSuspendModal(member)}
                                  className="p-2 text-orange-600 hover:bg-orange-50 rounded-lg transition-colors"
                                  title={member.status === 'suspended' ? 'Unsuspend' : 'Suspend'}
                                >
                                  {member.status === 'suspended' ? (
                                    <UserCheck className="w-4 h-4" />
                                  ) : (
                                    <UserX className="w-4 h-4" />
                                  )}
                                </button>
                                <button
                                  onClick={() => openRemoveModal(member)}
                                  className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                  title="Remove Member"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </>
                            ) : isCurrentUser ? (
                              <span className="text-sm text-gray-500">-</span>
                            ) : null}
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Role Change Modal */}
      <Modal
        isOpen={showRoleModal}
        onClose={() => setShowRoleModal(false)}
        title="Change Member Role"
      >
        <div className="space-y-4">
          <p className="text-gray-600">
            Change the role for <strong>{selectedMember?.name}</strong>
          </p>
          <Select
            label="New Role"
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
            options={[
              { value: 'analyst', label: 'Analyst' },
              { value: 'executive', label: 'Executive' },
            ]}
          />
          <div className="flex items-center justify-end space-x-3 pt-4">
            <Button
              variant="secondary"
              onClick={() => setShowRoleModal(false)}
              disabled={actionLoading}
            >
              Cancel
            </Button>
            <Button
              onClick={handleRoleChange}
              loading={actionLoading}
            >
              Update Role
            </Button>
          </div>
        </div>
      </Modal>

      {/* Suspend Modal */}
      <Modal
        isOpen={showSuspendModal}
        onClose={() => setShowSuspendModal(false)}
        title={selectedMember?.status === 'suspended' ? 'Unsuspend Member' : 'Suspend Member'}
      >
        <div className="space-y-4">
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <AlertCircle className="w-5 h-5 text-yellow-600 mt-0.5" />
              <div className="text-sm text-yellow-800">
                {selectedMember?.status === 'suspended' ? (
                  <p>
                    Are you sure you want to unsuspend <strong>{selectedMember?.name}</strong>? 
                    They will regain access to the workspace.
                  </p>
                ) : (
                  <p>
                    Are you sure you want to suspend <strong>{selectedMember?.name}</strong>? 
                    They will lose access to the workspace until unsuspended.
                  </p>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-end space-x-3 pt-4">
            <Button
              variant="secondary"
              onClick={() => setShowSuspendModal(false)}
              disabled={actionLoading}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleSuspend}
              loading={actionLoading}
            >
              {selectedMember?.status === 'suspended' ? 'Unsuspend' : 'Suspend'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Remove Modal */}
      <Modal
        isOpen={showRemoveModal}
        onClose={() => setShowRemoveModal(false)}
        title={selectedMember?.status === 'pending_registration' || selectedMember?.status === 'pending_acceptance' ? 'Remove Invitation' : 'Remove Member'}
      >
        <div className="space-y-4">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <AlertCircle className="w-5 h-5 text-red-600 mt-0.5" />
              <div className="text-sm text-red-800">
                <p className="font-medium mb-2">Are you sure?</p>
                {selectedMember?.status === 'pending_registration' || selectedMember?.status === 'pending_acceptance' ? (
                  <p>
                    Remove the invitation for <strong>{selectedMember?.email}</strong>? 
                    This will cancel the pending invitation.
                  </p>
                ) : (
                  <p>
                    Remove <strong>{selectedMember?.name}</strong> from the workspace? 
                    This action cannot be undone. They will need a new invitation to rejoin.
                  </p>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-end space-x-3 pt-4">
            <Button
              variant="secondary"
              onClick={() => setShowRemoveModal(false)}
              disabled={actionLoading}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleRemove}
              loading={actionLoading}
            >
              {selectedMember?.status === 'pending_registration' || selectedMember?.status === 'pending_acceptance' ? 'Remove Invitation' : 'Remove Member'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
    </AnimatedPage>
  )
}

export default MembersList

