from django.urls import path
from .views import (
    WorkspaceUpdateView,
    WorkspaceDetailByIdView,
    WorkspaceMembersView,
    InvitationView,
    RoleAssignmentView,
    MemberManageView,
    MemberSuspendView,
    MemberUnsuspendView,
    RemovePendingInvitationView,
    AcceptInvitationView,
)

app_name = 'workspace'

urlpatterns = [
    path('<int:workspace_id>/', WorkspaceDetailByIdView.as_view(), name='workspace-detail-by-id'),
    path('', WorkspaceUpdateView.as_view(), name='workspace-update'),
    path('members/', WorkspaceMembersView.as_view(), name='workspace-members'),
    path('invite/', InvitationView.as_view(), name='workspace-invite'),
    path('accept-invite/', AcceptInvitationView.as_view(), name='accept-invite'),
    path('invitation/<str:email>/', RemovePendingInvitationView.as_view(), name='remove-invitation'),
    path('member/<int:id>/', MemberManageView.as_view(), name='member-manage'),
    path('member/<int:id>/role/', RoleAssignmentView.as_view(), name='assign-role'),
    path('member/<int:id>/suspend/', MemberSuspendView.as_view(), name='suspend-member'),
    path('member/<int:id>/unsuspend/', MemberUnsuspendView.as_view(), name='unsuspend-member'),
]

