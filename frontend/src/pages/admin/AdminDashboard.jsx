import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'react-toastify'
import { BarChart3, CreditCard, Layers3, LogOut, Plus, Users, Building2 } from 'lucide-react'

import { adminAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import Card from '../../components/Card'
import Button from '../../components/Button'
import Modal from '../../components/Modal'
import Input from '../../components/Input'

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
})

const defaultForm = {
  name: '',
  description: '',
  badge: '',
  price_monthly: '29',
  price_yearly: '299',
  duration_days: '30',
  max_voice_requests: '100',
  has_mcp_access: false,
  features_text: '["Priority support", "Voice analytics", "Workspace insights"]',
  is_active: true,
}

function toFeatureList(features) {
  if (Array.isArray(features)) return features.map((item) => String(item))
  if (features && typeof features === 'object') {
    return Object.entries(features).map(([key, value]) => `${key}: ${value}`)
  }
  if (typeof features === 'string') {
    return features
      .split('\n')
      .join(',')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  }
  return []
}

function parseFeatures(value) {
  const trimmed = value.trim()
  if (!trimmed) return []

  try {
    return JSON.parse(trimmed)
  } catch {
    return trimmed
      .split('\n')
      .join(',')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  }
}

function AdminDashboard() {
  const navigate = useNavigate()
  const { logout } = useAuthStore()

  const [plans, setPlans] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [editingPlan, setEditingPlan] = useState(null)
  const [form, setForm] = useState(defaultForm)

  const sortedPlans = useMemo(
    () => [...plans].sort((a, b) => Number(a.price_monthly) - Number(b.price_monthly)),
    [plans]
  )

  const loadData = async () => {
    setLoading(true)
    try {
      const [plansResponse, statsResponse] = await Promise.all([adminAPI.listPlans(), adminAPI.getStats()])
      setPlans(plansResponse.data?.plans || [])
      setStats(statsResponse.data || null)
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load admin data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const openCreateModal = () => {
    setEditingPlan(null)
    setForm(defaultForm)
    setIsModalOpen(true)
  }

  const openEditModal = (plan) => {
    setEditingPlan(plan)
    setForm({
      name: plan.name || '',
      description: plan.description || '',
      badge: plan.badge || '',
      price_monthly: String(plan.price_monthly ?? ''),
      price_yearly: String(plan.price_yearly ?? ''),
      duration_days: String(plan.duration_days ?? 30),
      max_voice_requests: String(plan.max_voice_requests ?? 0),
      has_mcp_access: Boolean(plan.has_mcp_access),
      features_text: JSON.stringify(plan.features ?? [], null, 2),
      is_active: Boolean(plan.is_active),
    })
    setIsModalOpen(true)
  }

  const updateFormField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleSavePlan = async (event) => {
    event.preventDefault()
    setIsSaving(true)

    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim(),
        badge: form.badge.trim(),
        price_monthly: form.price_monthly,
        price_yearly: form.price_yearly,
        duration_days: Number(form.duration_days),
        max_voice_requests: Number(form.max_voice_requests),
        has_mcp_access: Boolean(form.has_mcp_access),
        features: parseFeatures(form.features_text),
        is_active: Boolean(form.is_active),
      }

      if (editingPlan) {
        await adminAPI.updatePlan(editingPlan.id, payload)
        toast.success('Plan updated successfully.')
      } else {
        await adminAPI.createPlan(payload)
        toast.success('Plan created successfully.')
      }

      setIsModalOpen(false)
      await loadData()
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to save plan')
    } finally {
      setIsSaving(false)
    }
  }

  const handleTogglePlan = async (plan) => {
    try {
      await adminAPI.updatePlan(plan.id, { is_active: !plan.is_active })
      toast.success(`Plan ${plan.is_active ? 'deactivated' : 'activated'} successfully.`)
      await loadData()
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to update plan status')
    }
  }

  const handleDeletePlan = async (planId) => {
    if (!window.confirm('Delete this plan permanently?')) {
      return
    }

    try {
      await adminAPI.deletePlan(planId)
      toast.success('Plan deleted successfully.')
      await loadData()
    } catch (error) {
      toast.error(error.response?.data?.message || 'Plan deletion is blocked by active usage')
    }
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-cyan-50 to-blue-100 p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">System Admin</p>
              <h1 className="mt-2 text-3xl font-semibold text-slate-900">Admin Dashboard</h1>
              <p className="mt-2 text-sm text-slate-600">
                Manage plans, monitor platform usage, and control subscription lifecycle.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Button onClick={openCreateModal}>
                <Plus className="h-4 w-4" />
                <span>Create Plan</span>
              </Button>
              <Button variant="outline" onClick={handleLogout}>
                <LogOut className="h-4 w-4" />
                <span>Logout</span>
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Card>
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-blue-100 p-3 text-blue-700">
                <Users className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-slate-600">Users</p>
                <p className="text-2xl font-semibold text-slate-900">{stats?.users?.total ?? 0}</p>
              </div>
            </div>
          </Card>
          <Card>
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-violet-100 p-3 text-violet-700">
                <Building2 className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-slate-600">Workspaces</p>
                <p className="text-2xl font-semibold text-slate-900">{stats?.workspaces?.total ?? 0}</p>
              </div>
            </div>
          </Card>
          <Card>
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-amber-100 p-3 text-amber-700">
                <Layers3 className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-slate-600">Active Subscriptions</p>
                <p className="text-2xl font-semibold text-slate-900">{stats?.subscriptions?.active ?? 0}</p>
              </div>
            </div>
          </Card>
          <Card>
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-emerald-100 p-3 text-emerald-700">
                <CreditCard className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-slate-600">Revenue</p>
                <p className="text-2xl font-semibold text-slate-900">
                  {currencyFormatter.format(Number(stats?.payments?.revenue || 0))}
                </p>
              </div>
            </div>
          </Card>
        </div>

        <Card
          title="Subscription Plans"
          subtitle="Create, edit, activate, and retire plans without disrupting existing subscriptions."
        >
          {loading ? (
            <p className="text-sm text-slate-600">Loading plans...</p>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {sortedPlans.map((plan) => {
                const features = toFeatureList(plan.features)
                return (
                  <div
                    key={plan.id}
                    className={`rounded-2xl border p-5 ${
                      plan.is_active ? 'border-slate-200 bg-white' : 'border-slate-200 bg-slate-50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-lg font-semibold text-slate-900">{plan.name}</p>
                        <p className="mt-1 text-xs text-slate-500">{plan.badge || 'No badge'}</p>
                      </div>
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                          plan.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-700'
                        }`}
                      >
                        {plan.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>

                    <p className="mt-3 text-sm text-slate-600">{plan.description || 'No description set.'}</p>

                    <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                      <div className="rounded-lg bg-slate-100 px-3 py-2">
                        <p className="text-xs text-slate-500">Monthly</p>
                        <p className="font-semibold text-slate-900">
                          {currencyFormatter.format(Number(plan.price_monthly || 0))}
                        </p>
                      </div>
                      <div className="rounded-lg bg-slate-100 px-3 py-2">
                        <p className="text-xs text-slate-500">Yearly</p>
                        <p className="font-semibold text-slate-900">
                          {currencyFormatter.format(Number(plan.price_yearly || 0))}
                        </p>
                      </div>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full bg-blue-100 px-2.5 py-1 text-blue-700">
                        {plan.duration_days} days
                      </span>
                      <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-indigo-700">
                        {plan.max_voice_requests} voice requests
                      </span>
                      <span
                        className={`rounded-full px-2.5 py-1 ${
                          plan.has_mcp_access ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-700'
                        }`}
                      >
                        {plan.has_mcp_access ? 'MCP On' : 'MCP Off'}
                      </span>
                    </div>

                    <div className="mt-4">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">
                        Features
                      </p>
                      <ul className="space-y-1 text-sm text-slate-700">
                        {(features.length > 0 ? features : ['No features configured']).map((feature) => (
                          <li key={`${plan.id}-${feature}`} className="flex items-center gap-2">
                            <BarChart3 className="h-3.5 w-3.5 text-cyan-600" />
                            <span>{feature}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="mt-5 grid grid-cols-2 gap-2">
                      <Button variant="outline" onClick={() => openEditModal(plan)}>
                        Edit
                      </Button>
                      <Button variant={plan.is_active ? 'secondary' : 'success'} onClick={() => handleTogglePlan(plan)}>
                        {plan.is_active ? 'Deactivate' : 'Activate'}
                      </Button>
                    </div>
                    <div className="mt-2">
                      <Button variant="danger" fullWidth onClick={() => handleDeletePlan(plan.id)}>
                        Delete
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </div>

      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={editingPlan ? 'Edit Plan' : 'Create Plan'}
        size="lg"
        panelClassName="max-h-[85vh]"
        contentClassName="p-0"
        scrollContent={false}
        overlayScrollable={false}
      >
        <form className="flex h-full flex-col" onSubmit={handleSavePlan}>
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 sm:px-4 sm:py-4">
            <div className="grid gap-3 md:grid-cols-2">
              <Input
                label="Plan Name"
                value={form.name}
                required
                className="px-3 py-1.5 text-sm"
                onChange={(event) => updateFormField('name', event.target.value)}
              />
              <Input
                label="Badge"
                value={form.badge}
                className="px-3 py-1.5 text-sm"
                onChange={(event) => updateFormField('badge', event.target.value)}
                placeholder="Popular"
              />

              <div className="md:col-span-2">
                <Input
                  label="Description"
                  value={form.description}
                  className="px-3 py-1.5 text-sm"
                  onChange={(event) => updateFormField('description', event.target.value)}
                  placeholder="Plan summary"
                />
              </div>

              <Input
                label="Monthly Price"
                type="number"
                min="0"
                step="0.01"
                value={form.price_monthly}
                required
                className="px-3 py-1.5 text-sm"
                onChange={(event) => updateFormField('price_monthly', event.target.value)}
              />
              <Input
                label="Yearly Price"
                type="number"
                min="0"
                step="0.01"
                value={form.price_yearly}
                required
                className="px-3 py-1.5 text-sm"
                onChange={(event) => updateFormField('price_yearly', event.target.value)}
              />

              <Input
                label="Duration (days)"
                type="number"
                min="1"
                value={form.duration_days}
                required
                className="px-3 py-1.5 text-sm"
                onChange={(event) => updateFormField('duration_days', event.target.value)}
              />
              <Input
                label="Max Voice Requests"
                type="number"
                min="1"
                value={form.max_voice_requests}
                required
                className="px-3 py-1.5 text-sm"
                onChange={(event) => updateFormField('max_voice_requests', event.target.value)}
              />

              <div className="md:col-span-2">
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Features (JSON or comma/new line)
                </label>
                <textarea
                  value={form.features_text}
                  onChange={(event) => updateFormField('features_text', event.target.value)}
                  rows={4}
                  className="input w-full px-3 py-1.5 text-sm"
                />
              </div>

              <div className="flex flex-wrap items-center gap-3 md:col-span-2">
                <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={form.has_mcp_access}
                    onChange={(event) => updateFormField('has_mcp_access', event.target.checked)}
                  />
                  MCP Access
                </label>
                <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(event) => updateFormField('is_active', event.target.checked)}
                  />
                  Active Plan
                </label>
              </div>
            </div>
          </div>

          <div className="sticky bottom-0 border-t bg-white px-3 py-2 sm:px-4 sm:py-3">
            <div className="flex items-center justify-end gap-2 sm:gap-3">
              <Button type="button" variant="secondary" size="sm" onClick={() => setIsModalOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" size="sm" loading={isSaving}>
                {editingPlan ? 'Save Changes' : 'Create Plan'}
              </Button>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  )
}

export default AdminDashboard
