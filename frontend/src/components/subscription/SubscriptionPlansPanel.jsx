import { useEffect, useMemo, useState } from 'react'
import { Check, CreditCard, Landmark, Sparkles, ShieldCheck, Zap } from 'lucide-react'
import { toast } from 'react-toastify'

import Card from '../Card'
import Button from '../Button'
import { subscriptionAPI } from '../../api/endpoints'

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
})

const BANK_OPTIONS = [
  'All Major Banks',
  'Bank of America',
  'HSBC',
  'Deutsche Bank',
  'BNP Paribas',
  'Barclays',
  'JPMorgan Chase',
  'Standard Chartered',
]

function normalizeFeatures(features) {
  if (Array.isArray(features)) {
    return features.map((item) => String(item)).filter(Boolean)
  }

  if (features && typeof features === 'object') {
    return Object.entries(features)
      .filter(([, value]) => Boolean(value))
      .map(([key, value]) => (value === true ? key : `${key}: ${value}`))
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

function planBadgeLabel(plan) {
  if (plan.badge) return plan.badge
  if (plan.has_mcp_access) return 'MCP Ready'
  return ''
}

function SubscriptionPlansPanel({ workspaceId, onSubscribed, title = 'Choose Your Plan' }) {
  const [plans, setPlans] = useState([])
  const [currentSubscription, setCurrentSubscription] = useState(null)
  const [selectedPlanId, setSelectedPlanId] = useState(null)
  const [paymentMethod, setPaymentMethod] = useState('visa')
  const [bankSearch, setBankSearch] = useState('')
  const [selectedBank, setSelectedBank] = useState('')
  const [bankAccountNumber, setBankAccountNumber] = useState('')
  const [bankAccountName, setBankAccountName] = useState('')
  const [cardForm, setCardForm] = useState({
    cardNumber: '',
    cardHolderName: '',
    expiryDate: '',
    cvv: '',
  })
  const [formErrors, setFormErrors] = useState({})
  const [loading, setLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const recommendedPlanId = useMemo(() => {
    const byBadge = plans.find((plan) =>
      String(plan.badge || '')
        .toLowerCase()
        .match(/popular|best value|recommended/)
    )
    if (byBadge) return byBadge.id
    if (plans.length === 0) return null
    return plans[Math.floor(plans.length / 2)].id
  }, [plans])

  const selectedPlan = useMemo(
    () => plans.find((plan) => plan.id === selectedPlanId) || null,
    [plans, selectedPlanId]
  )

  const filteredBanks = useMemo(
    () =>
      BANK_OPTIONS.filter((bank) => bank.toLowerCase().includes(bankSearch.trim().toLowerCase())),
    [bankSearch]
  )

  const loadPlans = async () => {
    setLoading(true)
    try {
      const plansResponse = await subscriptionAPI.listPlans()
      setPlans(plansResponse.data?.plans || [])

      if (workspaceId) {
        const currentResponse = await subscriptionAPI.getCurrentSubscription(workspaceId)
        setCurrentSubscription(currentResponse.data?.subscription || null)
      }
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load subscription plans')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPlans()
  }, [workspaceId])

  useEffect(() => {
    if (selectedPlanId && !plans.some((plan) => plan.id === selectedPlanId)) {
      setSelectedPlanId(null)
    }
  }, [plans, selectedPlanId])

  const resetPaymentErrors = () => {
    setFormErrors({})
  }

  const validatePayment = () => {
    const nextErrors = {}

    if (!selectedPlanId) {
      nextErrors.selectedPlan = 'Please select a plan first.'
    }

    if (paymentMethod === 'bank') {
      const accountNumberDigits = bankAccountNumber.replace(/\D/g, '')
      if (!selectedBank) {
        nextErrors.selectedBank = 'Please select a bank.'
      }
      if (accountNumberDigits.length < 6 || accountNumberDigits.length > 20) {
        nextErrors.bankAccountNumber = 'Account number must be 6-20 digits.'
      }
      if (bankAccountName.trim().length < 2) {
        nextErrors.bankAccountName = 'Account name is required.'
      }
    }

    if (paymentMethod === 'visa') {
      const cardDigits = cardForm.cardNumber.replace(/\D/g, '')
      const cvvDigits = cardForm.cvv.replace(/\D/g, '')
      if (cardDigits.length < 13 || cardDigits.length > 19) {
        nextErrors.cardNumber = 'Card number must be 13-19 digits.'
      }
      if (cardForm.cardHolderName.trim().length < 2) {
        nextErrors.cardHolderName = 'Card holder name is required.'
      }
      if (!/^(0[1-9]|1[0-2])\/\d{2}$/.test(cardForm.expiryDate.trim())) {
        nextErrors.expiryDate = 'Use MM/YY format.'
      }
      if (cvvDigits.length < 3 || cvvDigits.length > 4) {
        nextErrors.cvv = 'CVV must be 3 or 4 digits.'
      }
    }

    setFormErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const handleSubscribe = async () => {
    if (!workspaceId) {
      toast.error('Workspace is required to activate a subscription.')
      return
    }

    if (!validatePayment()) {
      toast.error('Please complete the payment form.')
      return
    }

    setIsSubmitting(true)
    try {
      const response = await subscriptionAPI.subscribe({
        workspace_id: workspaceId,
        plan_id: selectedPlanId,
        payment_method: paymentMethod,
      })

      if (response.data?.success) {
        toast.success('Subscription activated successfully.')
        if (response.data?.subscription) {
          setCurrentSubscription(response.data.subscription)
          setSelectedPlanId(response.data.subscription.plan?.id || selectedPlanId)
        }
        onSubscribed?.(response.data)
        await loadPlans()
      } else {
        toast.error(response.data?.message || 'Subscription failed.')
      }
    } catch (error) {
      toast.error(error.response?.data?.message || 'Subscription request failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-emerald-100 bg-gradient-to-r from-emerald-50 via-cyan-50 to-blue-50 p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">Subscription</p>
        <h2 className="mt-2 text-2xl font-semibold text-slate-900">{title}</h2>
        <p className="mt-2 text-sm text-slate-600">
          Pick a plan and activate instantly. Payment is simulated and always succeeds in this environment.
        </p>
      </div>

      {currentSubscription && (
        <Card className="border border-blue-200 bg-blue-50/60">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Current Plan</p>
              <h3 className="text-lg font-semibold text-slate-900">{currentSubscription.plan?.name}</h3>
              <p className="text-sm text-slate-600">
                Active until {currentSubscription.end_date || 'N/A'}.
              </p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-sm font-medium text-blue-700">
              <ShieldCheck className="h-4 w-4" />
              Active
            </div>
          </div>
        </Card>
      )}

      {loading ? (
        <Card>
          <p className="text-sm text-slate-600">Loading available plans...</p>
        </Card>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {plans.map((plan) => {
            const currentPlanId = currentSubscription?.plan?.id
            const isCurrent = currentPlanId === plan.id
            const isRecommended = recommendedPlanId === plan.id
            const badge = planBadgeLabel(plan)
            const features = normalizeFeatures(plan.features)

            return (
              <div
                key={plan.id}
                className={`relative rounded-2xl border p-5 shadow-sm transition ${
                  isRecommended
                    ? 'border-amber-300 bg-gradient-to-b from-amber-50 to-white'
                    : 'border-slate-200 bg-white'
                }`}
              >
                {isRecommended && (
                  <div className="absolute -top-3 left-4 inline-flex items-center gap-1 rounded-full bg-amber-500 px-3 py-1 text-xs font-semibold text-white">
                    <Sparkles className="h-3.5 w-3.5" />
                    Recommended
                  </div>
                )}

                {badge && (
                  <div className="mt-2 inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                    {badge}
                  </div>
                )}

                <h3 className="mt-3 text-xl font-semibold text-slate-900">{plan.name}</h3>
                <p className="mt-2 min-h-[40px] text-sm text-slate-600">{plan.description || 'Subscription plan'}</p>

                <div className="mt-4 flex items-end gap-2">
                  <p className="text-2xl font-bold text-slate-900">
                    {currencyFormatter.format(Number(plan.price_monthly || 0))}
                  </p>
                  <p className="pb-1 text-xs uppercase tracking-[0.12em] text-slate-500">/ month</p>
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  {currencyFormatter.format(Number(plan.price_yearly || 0))} yearly
                </p>

                <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div className="rounded-lg bg-slate-100 px-3 py-2 text-slate-700">
                    <p className="font-semibold text-slate-900">{plan.duration_days} days</p>
                    <p>Duration</p>
                  </div>
                  <div className="rounded-lg bg-slate-100 px-3 py-2 text-slate-700">
                    <p className="font-semibold text-slate-900">{plan.max_voice_requests}</p>
                    <p>Voice Requests</p>
                  </div>
                </div>

                <div className="mt-4 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium">
                  <Zap
                    className={`h-3.5 w-3.5 ${plan.has_mcp_access ? 'text-emerald-600' : 'text-slate-400'}`}
                  />
                  <span className={plan.has_mcp_access ? 'text-emerald-700' : 'text-slate-500'}>
                    {plan.has_mcp_access ? 'MCP Enabled' : 'MCP Not Included'}
                  </span>
                </div>

                <ul className="mt-4 space-y-2 text-sm text-slate-700">
                  {(features.length > 0 ? features : ['Basic analytics support']).map((feature) => (
                    <li key={`${plan.id}-${feature}`} className="flex items-start gap-2">
                      <Check className="mt-0.5 h-4 w-4 text-emerald-600" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-5">
                  <Button
                    fullWidth
                    onClick={() => {
                      setSelectedPlanId(plan.id)
                      resetPaymentErrors()
                    }}
                    disabled={isCurrent}
                    variant={selectedPlanId === plan.id ? 'secondary' : 'primary'}
                  >
                    {isCurrent ? 'Current Plan' : selectedPlanId === plan.id ? 'Selected' : 'Select Plan'}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {!selectedPlan ? (
        <Card className="border border-slate-200 bg-slate-50">
          <p className="text-sm text-slate-600">Select a plan to reveal payment options.</p>
        </Card>
      ) : (
        <Card className="border border-slate-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Payment</p>
              <h3 className="mt-1 text-lg font-semibold text-slate-900">Complete Subscription</h3>
              <p className="mt-1 text-sm text-slate-600">
                Selected plan: <span className="font-semibold text-slate-900">{selectedPlan.name}</span>
              </p>
            </div>
            <div className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
              {currencyFormatter.format(Number(selectedPlan.price_monthly || 0))} / month
            </div>
          </div>

          <div className="mt-5 space-y-4">
            <div className="inline-flex items-center rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
              <button
                type="button"
                onClick={() => {
                  setPaymentMethod('visa')
                  resetPaymentErrors()
                }}
                className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition ${
                  paymentMethod === 'visa'
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <CreditCard className="h-4 w-4" />
                Visa
              </button>
              <button
                type="button"
                onClick={() => {
                  setPaymentMethod('bank')
                  resetPaymentErrors()
                }}
                className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition ${
                  paymentMethod === 'bank'
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <Landmark className="h-4 w-4" />
                Bank Transfer
              </button>
            </div>

            {paymentMethod === 'bank' ? (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="mb-2 block text-sm font-medium text-gray-700">Search Bank (Optional)</label>
                  <input
                    type="text"
                    value={bankSearch}
                    onChange={(event) => setBankSearch(event.target.value)}
                    className="input w-full"
                    placeholder="Type to filter banks"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="mb-2 block text-sm font-medium text-gray-700">Bank</label>
                  <select
                    value={selectedBank}
                    onChange={(event) => setSelectedBank(event.target.value)}
                    className={`input w-full ${formErrors.selectedBank ? 'border-red-500 focus:ring-red-500' : ''}`}
                  >
                    <option value="">Select a bank</option>
                    {filteredBanks.map((bank) => (
                      <option key={bank} value={bank}>
                        {bank}
                      </option>
                    ))}
                  </select>
                  {formErrors.selectedBank && <p className="mt-1 text-sm text-red-600">{formErrors.selectedBank}</p>}
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Account Number</label>
                  <input
                    type="text"
                    value={bankAccountNumber}
                    onChange={(event) => setBankAccountNumber(event.target.value)}
                    className={`input w-full ${formErrors.bankAccountNumber ? 'border-red-500 focus:ring-red-500' : ''}`}
                    placeholder="1234567890"
                  />
                  {formErrors.bankAccountNumber && (
                    <p className="mt-1 text-sm text-red-600">{formErrors.bankAccountNumber}</p>
                  )}
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Account Name</label>
                  <input
                    type="text"
                    value={bankAccountName}
                    onChange={(event) => setBankAccountName(event.target.value)}
                    className={`input w-full ${formErrors.bankAccountName ? 'border-red-500 focus:ring-red-500' : ''}`}
                    placeholder="Account holder name"
                  />
                  {formErrors.bankAccountName && (
                    <p className="mt-1 text-sm text-red-600">{formErrors.bankAccountName}</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="mb-2 block text-sm font-medium text-gray-700">Card Number</label>
                  <input
                    type="text"
                    value={cardForm.cardNumber}
                    onChange={(event) =>
                      setCardForm((prev) => ({
                        ...prev,
                        cardNumber: event.target.value,
                      }))
                    }
                    className={`input w-full ${formErrors.cardNumber ? 'border-red-500 focus:ring-red-500' : ''}`}
                    placeholder="4111 1111 1111 1111"
                  />
                  {formErrors.cardNumber && <p className="mt-1 text-sm text-red-600">{formErrors.cardNumber}</p>}
                </div>

                <div className="md:col-span-2">
                  <label className="mb-2 block text-sm font-medium text-gray-700">Card Holder Name</label>
                  <input
                    type="text"
                    value={cardForm.cardHolderName}
                    onChange={(event) =>
                      setCardForm((prev) => ({
                        ...prev,
                        cardHolderName: event.target.value,
                      }))
                    }
                    className={`input w-full ${formErrors.cardHolderName ? 'border-red-500 focus:ring-red-500' : ''}`}
                    placeholder="John Doe"
                  />
                  {formErrors.cardHolderName && (
                    <p className="mt-1 text-sm text-red-600">{formErrors.cardHolderName}</p>
                  )}
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Expiry Date (MM/YY)</label>
                  <input
                    type="text"
                    value={cardForm.expiryDate}
                    onChange={(event) =>
                      setCardForm((prev) => ({
                        ...prev,
                        expiryDate: event.target.value,
                      }))
                    }
                    className={`input w-full ${formErrors.expiryDate ? 'border-red-500 focus:ring-red-500' : ''}`}
                    placeholder="12/29"
                  />
                  {formErrors.expiryDate && <p className="mt-1 text-sm text-red-600">{formErrors.expiryDate}</p>}
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">CVV</label>
                  <input
                    type="text"
                    value={cardForm.cvv}
                    onChange={(event) =>
                      setCardForm((prev) => ({
                        ...prev,
                        cvv: event.target.value,
                      }))
                    }
                    className={`input w-full ${formErrors.cvv ? 'border-red-500 focus:ring-red-500' : ''}`}
                    placeholder="123"
                  />
                  {formErrors.cvv && <p className="mt-1 text-sm text-red-600">{formErrors.cvv}</p>}
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-end gap-3 pt-1">
              <Button
                type="button"
                onClick={handleSubscribe}
                loading={isSubmitting}
                disabled={currentSubscription?.plan?.id === selectedPlanId}
              >
                {currentSubscription?.plan?.id === selectedPlanId ? 'Subscribed' : 'Subscribe'}
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}

export default SubscriptionPlansPanel
