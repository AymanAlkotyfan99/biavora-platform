from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from .models import Workspace, WorkspaceMember, Invitation
from .serializers import (
    WorkspaceUpdateSerializer, 
    WorkspaceMemberSerializer, 
    WorkspaceSerializer,
    InvitationSerializer,
    RoleAssignmentSerializer
)
from users.utils import generate_invitation_token, send_invitation_email
from .notification_client import get_notification_client
from users.models import User
from users.permissions import IsAdmin
import logging

logger = logging.getLogger(__name__)


class WorkspaceDetailByIdView(APIView):
    """
    Service-to-service and API lookup: GET /workspace/<id>/

    Returns workspace metadata including ``manager_id`` (workspace owner user id)
    for downstream BI services (voice-service) that resolve dataset binding context.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        user = request.user

        if not user.is_verified:
            return Response(
                {
                    "success": False,
                    "message": "Please verify your email before accessing workspace features.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            workspace = Workspace.objects.select_related("owner").get(id=workspace_id)
        except Workspace.DoesNotExist:
            return Response(
                {"success": False, "message": "Workspace not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.role == "manager" and workspace.owner_id == user.id:
            allowed = True
        elif WorkspaceMember.objects.filter(
            workspace=workspace,
            user=user,
            status="active",
        ).exists():
            allowed = True
        elif workspace.owner_id == user.id:
            allowed = True
        else:
            allowed = False

        if not allowed:
            return Response(
                {"success": False, "message": "You do not have access to this workspace."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace_serializer = WorkspaceSerializer(workspace)
        owner = workspace.owner
        return Response(
            {
                "success": True,
                "id": workspace.id,
                "manager_id": workspace.owner_id,
                "workspace": workspace_serializer.data,
                "owner": {
                    "id": owner.id,
                    "name": owner.name,
                    "email": owner.email,
                },
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceUpdateView(APIView):
    """
    API endpoint for updating workspace information.
    
    PUT /workspace/
    
    Only the workspace owner (Manager) can update workspace info.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Return current workspace details for the authenticated manager.
        """
        user = request.user

        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Workspace not found. Only managers can access workspace information.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        workspace_serializer = WorkspaceSerializer(workspace)
        return Response(
            {
                'success': True,
                'workspace': workspace_serializer.data,
            },
            status=status.HTTP_200_OK
        )
    
    def put(self, request):
        """
        Update workspace information (name and/or description).
        
        Input:
            - name (optional): New workspace name
            - description (optional): New workspace description
            
        Business Rules:
            - Only workspace owner can update
            - Can update name and description only
            - Cannot update owner, id, or created_at
            - User must be verified to access workspace
            
        Output:
            - success: Boolean
            - message: Status message
            - workspace: Updated workspace info
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get user's owned workspace (managers only have one workspace)
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Workspace not found. Only managers can update workspace information.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = WorkspaceUpdateSerializer(
            data=request.data,
            context={'request': request, 'workspace': workspace}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Update the workspace
            updated_workspace = serializer.update(workspace, serializer.validated_data)
            
            # Return updated workspace info
            workspace_serializer = WorkspaceSerializer(updated_workspace)
            
            logger.info(f"Workspace {updated_workspace.id} updated by {user.email}")
            
            return Response(
                {
                    'success': True,
                    'message': 'Workspace updated successfully.',
                    'workspace': workspace_serializer.data
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': str(e.detail[0]) if isinstance(e.detail, list) else str(e.detail)
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        except Exception as e:
            logger.error(f"Error updating workspace for user {user.email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while updating workspace'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkspaceMembersView(APIView):
    """
    API endpoint for viewing workspace members list.
    
    GET /workspace/members/
    
    Any user who belongs to the workspace can view the member list.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get list of all members in the user's workspace.
        
        Business Rules:
            - Managers: Can view ALL members (active + pending + invited)
            - Analysts/Executives: Can view only active members
            - User must be verified to access workspace
            
        Output:
            - workspace_id: ID of the workspace
            - workspace_name: Name of the workspace
            - accepted_members: List of active members
            - pending_members: List of pending acceptance members (Manager only)
            - invited_members: List of pending registration members (Manager only)
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Determine workspace based on user role
        if user.role == 'manager':
            # Manager: Get owned workspace
            try:
                workspace = Workspace.objects.get(owner=user)
            except Workspace.DoesNotExist:
                return Response(
                    {
                        'success': False,
                        'message': 'Workspace not found.'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get all workspace members
            all_members = WorkspaceMember.objects.filter(
                workspace=workspace
            ).select_related('user')
            
            # Categorize members
            accepted_members = []
            pending_members = []
            invited_members = []
            
            # Add owner (manager) to accepted members first
            accepted_members.append({
                'id': user.id,
                'name': user.name,
                'email': user.email,
                'role': 'manager',
                'status': 'suspended' if not user.is_active else 'active'
            })
            
            # Categorize workspace members
            for member in all_members:
                # Check if user is verified - unverified users should show as pending
                is_user_verified = member.user.is_verified if member.user else False
                
                if member.status == 'active':
                    # If user is not verified, show as pending even if status is active
                    if not is_user_verified:
                        pending_members.append({
                            'id': member.user.id if member.user else None,
                            'name': member.user.name if member.user else 'Not registered',
                            'email': member.invited_email,
                            'role': member.role,
                            'status': 'pending_acceptance'
                        })
                    else:
                        accepted_members.append({
                            'id': member.user.id if member.user else None,
                            'name': member.user.name if member.user else 'Not registered',
                            'email': member.invited_email,
                            'role': member.role,
                            'status': 'suspended' if (member.user and not member.user.is_active) else 'active'
                        })
                elif member.status == 'pending_acceptance':
                    pending_members.append({
                        'id': member.user.id if member.user else None,
                        'name': member.user.name if member.user else 'Not registered',
                        'email': member.invited_email,
                        'role': member.role,
                        'status': 'pending_acceptance'
                    })
                elif member.status == 'pending_registration':
                    invited_members.append({
                        'id': None,
                        'name': 'Not registered yet',
                        'email': member.invited_email,
                        'role': member.role,
                        'status': 'pending_registration'
                    })
                elif member.status == 'suspended':
                    accepted_members.append({
                        'id': member.user.id if member.user else None,
                        'name': member.user.name if member.user else 'Not registered',
                        'email': member.invited_email,
                        'role': member.role,
                        'status': 'suspended'
                    })
            
            return Response(
                {
                    'workspace_id': workspace.id,
                    'workspace_name': workspace.name,
                    'accepted_members': accepted_members,
                    'pending_members': pending_members,
                    'invited_members': invited_members,
                    'members': accepted_members  # For backward compatibility
                },
                status=status.HTTP_200_OK
            )
        else:
            # Analyst/Executive: Get workspaces they are members of
            memberships = WorkspaceMember.objects.filter(
                user=user,
                status='active'
            ).select_related('workspace')
            
            if not memberships.exists():
                return Response(
                    {
                        'success': False,
                        'message': 'You are not a member of any workspace.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Return members of the first workspace they belong to
            membership = memberships.first()
            workspace = membership.workspace
            
            # Get only active members for non-managers
            active_members = WorkspaceMember.objects.filter(
                workspace=workspace,
                status='active'
            ).select_related('user')
            
            accepted_members = []
            
            # Add owner (manager) first
            owner = workspace.owner
            accepted_members.append({
                'id': owner.id,
                'name': owner.name,
                'email': owner.email,
                'role': 'manager',
                'status': 'suspended' if not owner.is_active else 'active'
            })
            
            # Add other active members
            for member in active_members:
                if member.user:
                    accepted_members.append({
                        'id': member.user.id,
                        'name': member.user.name,
                        'email': member.user.email,
                        'role': member.role,
                        'status': 'suspended' if not member.user.is_active else 'active'
                    })
            
            return Response(
                {
                    'workspace_id': workspace.id,
                    'workspace_name': workspace.name,
                    'accepted_members': accepted_members,
                    'pending_members': [],
                    'invited_members': [],
                    'members': accepted_members  # For backward compatibility
                },
                status=status.HTTP_200_OK
            )


class InvitationView(APIView):
    """
    API endpoint for inviting members to workspace (R9).
    
    POST /workspace/invite/
    
    Only the workspace owner (Manager) can send invitations.
    """
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def post(self, request):
        """
        Send workspace invitation to a new member.
        
        Input:
            - email: Email of the person to invite
            - role: Role to assign (analyst or executive)
            
        Business Rules:
            - Only workspace owner can invite
            - Cannot invite existing members
            - Cannot send duplicate pending invitations
            - Creates WorkspaceMember placeholder immediately
            - If user doesn't exist: status = "pending_registration"
            - If user exists but not accepted: status = "pending_acceptance"
            - Invitation expires in 48 hours
            - Real email sent via Gmail SMTP
            - User must be verified to access workspace
            
        Output:
            - success: Boolean
            - message: Status message
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = InvitationSerializer(
            data=request.data,
            context={'request': request}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Extract validated data
            invited_email = serializer.validated_data['email']
            role = serializer.validated_data['role']
            workspace = serializer.validated_data['workspace']
            
            # === CLEANUP: Expire old invitations and remove old pending members ===
            # This allows re-inviting removed users
            
            # Expire ALL old invitations for this email in this workspace
            # (both pending and accepted - to allow re-invitation after removal)
            Invitation.objects.filter(
                invited_email=invited_email,
                workspace=workspace,
                status__in=['pending', 'accepted']
            ).update(status='expired')
            
            # Remove any old pending WorkspaceMember entries for this email
            # (from previous invitations that weren't accepted)
            WorkspaceMember.objects.filter(
                workspace=workspace,
                invited_email=invited_email,
                status__in=['pending_registration', 'pending_acceptance']
            ).delete()
            
            # Check if user exists
            try:
                existing_user = User.objects.get(email=invited_email)
                user_exists = True
            except User.DoesNotExist:
                existing_user = None
                user_exists = False
            
            # Generate unique invitation token (NOT verification token!)
            # This is a simple UUID-based token stored in Invitation model
            token = generate_invitation_token()
            
            # Create invitation record
            invitation = Invitation.objects.create(
                invited_email=invited_email,
                workspace=workspace,
                role=role,
                token=token,
                status='pending'
            )
            
            # Create WorkspaceMember placeholder entry
            if user_exists:
                # User exists - create entry with pending_acceptance status
                WorkspaceMember.objects.create(
                    workspace=workspace,
                    user=existing_user,
                    invited_email=invited_email,
                    role=role,
                    status='pending_acceptance'
                )
            else:
                # User doesn't exist - create entry with pending_registration status
                WorkspaceMember.objects.create(
                    workspace=workspace,
                    user=None,
                    invited_email=invited_email,
                    role=role,
                    status='pending_registration'
                )
            
            # Send invitation email with role information
            logger.info(
                f"Attempting to send invitation email to {invited_email} for workspace {workspace.id} "
                f"by {request.user.email} (user_exists: {user_exists})"
            )
            
            notification_client = get_notification_client()
            notification_result = notification_client.send_event(
                event_type='workspace_invitation',
                event_key=f"workspace-invitation:{workspace.id}:{token}",
                payload={
                    'invited_email': invited_email,
                    'inviter_name': request.user.name,
                    'workspace_name': workspace.name,
                    'token': token,
                    'role': role,
                },
            )
            email_sent = notification_result.get('success', False)

            # Transitional fallback to preserve invitation delivery if
            # notification-service is temporarily unavailable.
            if not email_sent:
                email_sent = send_invitation_email(
                    invited_email=invited_email,
                    inviter_name=request.user.name,
                    workspace_name=workspace.name,
                    token=token,
                    role=role
                )
            
            if not email_sent:
                logger.error(
                    f"Invitation created but email failed to send for {invited_email}. "
                    f"Check email configuration and SMTP settings."
                )
            else:
                logger.info(
                    f"Invitation email sent successfully to {invited_email} for workspace {workspace.id} "
                    f"by {request.user.email}"
                )
            
            logger.info(
                f"Invitation processed for {invited_email} in workspace {workspace.id} "
                f"by {request.user.email} (user_exists: {user_exists}, email_sent: {email_sent})"
            )
            
            return Response(
                {
                    'success': True,
                    'message': 'Invitation sent successfully.'
                },
                status=status.HTTP_201_CREATED
            )
            
        except serializers.ValidationError as e:
            # Extract error message
            if isinstance(e.detail, dict):
                error_message = str(list(e.detail.values())[0][0])
            elif isinstance(e.detail, list):
                error_message = str(e.detail[0])
            else:
                error_message = str(e.detail)
            
            return Response(
                {
                    'success': False,
                    'message': error_message
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(
                f"Error sending invitation from {request.user.email}: {str(e)}"
            )
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while sending invitation'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RoleAssignmentView(APIView):
    """
    API endpoint for assigning/updating member roles (R10).
    
    PUT /workspace/member/<id>/role/
    
    Only the workspace owner (Manager) can assign roles.
    """
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def put(self, request, id):
        """
        Update the role of a workspace member.
        
        Input:
            - role: New role (manager, analyst, or executive)
            
        Business Rules:
            - Only workspace owner can assign roles
            - Cannot change own role
            - Cannot demote another manager
            - Member must belong to workspace
            - User must be verified to access workspace
            
        Output:
            - success: Boolean
            - message: Status message
            - member: Updated member info
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = RoleAssignmentSerializer(
            data=request.data,
            context={'request': request, 'member_id': id}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Extract validated data
            member = serializer.validated_data['member']
            new_role = serializer.validated_data['role']
            workspace = serializer.validated_data['workspace']
            
            # Update role in BOTH User model AND WorkspaceMember model
            old_role = member.role
            
            # Update User role
            member.role = new_role
            member.save()
            
            # Update WorkspaceMember role (critical for consistency!)
            try:
                workspace_member = WorkspaceMember.objects.get(
                    workspace=workspace,
                    user=member
                )
                workspace_member.role = new_role
                workspace_member.save()
                logger.info(
                    f"Updated WorkspaceMember role for {member.email} to {new_role}"
                )
            except WorkspaceMember.DoesNotExist:
                logger.warning(
                    f"WorkspaceMember not found for {member.email} in workspace {workspace.id}"
                )
            
            logger.info(
                f"Role updated for user {member.email} from {old_role} to {new_role} "
                f"in workspace {workspace.id} by {request.user.email}"
            )
            
            return Response(
                {
                    'success': True,
                    'message': 'Role updated successfully.',
                    'member': {
                        'id': member.id,
                        'name': member.name,
                        'email': member.email,
                        'role': member.role
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            # Extract error message
            if isinstance(e.detail, dict):
                error_message = str(list(e.detail.values())[0][0])
            elif isinstance(e.detail, list):
                error_message = str(e.detail[0])
            else:
                error_message = str(e.detail)
            
            return Response(
                {
                    'success': False,
                    'message': error_message
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        except Exception as e:
            logger.error(
                f"Error assigning role by {request.user.email}: {str(e)}"
            )
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while assigning role'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MemberManageView(APIView):
    """
    API endpoint for managing workspace members (R11).
    
    GET    /workspace/member/<id>/ - View member details
    PUT    /workspace/member/<id>/ - Update member status
    DELETE /workspace/member/<id>/ - Remove member from workspace
    
    Manager can perform all actions. Members can only view themselves.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, id):
        """
        Get detailed information about a workspace member.
        
        Business Rules:
            - Manager can view any member in their workspace
            - Members can view their own details
            - User must be verified to access workspace
            
        Output:
            - id, name, email, role, status
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get the target member
        try:
            member = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Member not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions
        if user.role == 'manager':
            # Manager: check if member is in their workspace
            try:
                workspace = Workspace.objects.get(owner=user)
                is_member = WorkspaceMember.objects.filter(
                    workspace=workspace,
                    user=member
                ).exists()
                
                if not is_member and member != workspace.owner:
                    return Response(
                        {
                            'success': False,
                            'message': 'This user is not a member of your workspace.'
                        },
                        status=status.HTTP_403_FORBIDDEN
                    )
            except Workspace.DoesNotExist:
                return Response(
                    {
                        'success': False,
                        'message': 'Workspace not found.'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Non-manager can only view themselves
            if member.id != user.id:
                return Response(
                    {
                        'success': False,
                        'message': 'You can only view your own details.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Return member details
        from .serializers import MemberDetailSerializer
        serializer = MemberDetailSerializer(member)
        
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @transaction.atomic
    def put(self, request, id):
        """
        Update member status (active/pending).
        
        Business Rules:
            - Only manager can update
            - Can update status field
            - User must be verified to access workspace
            
        Output:
            - Updated member info
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        from .serializers import MemberUpdateSerializer
        
        serializer = MemberUpdateSerializer(
            data=request.data,
            context={'request': request, 'member_id': id}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            member = serializer.validated_data['member']
            new_status = serializer.validated_data.get('status')
            
            # Update status
            if new_status == 'active':
                member.is_active = True
                member.is_verified = True
            elif new_status == 'pending':
                member.is_verified = False
            
            member.save()
            
            logger.info(f"Member {member.email} status updated to {new_status} by {request.user.email}")
            
            # Return updated member info
            from .serializers import MemberDetailSerializer
            member_serializer = MemberDetailSerializer(member)
            
            return Response(
                member_serializer.data,
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            if isinstance(e.detail, dict):
                error_message = str(list(e.detail.values())[0][0])
            elif isinstance(e.detail, list):
                error_message = str(e.detail[0])
            else:
                error_message = str(e.detail)
            
            return Response(
                {
                    'success': False,
                    'message': error_message
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        except Exception as e:
            logger.error(f"Error updating member {id} by {request.user.email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while updating member'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @transaction.atomic
    def delete(self, request, id):
        """
        Remove member from workspace.
        
        Business Rules:
            - Only manager can remove
            - Cannot remove self
            - Removes WorkspaceMember entry
            - User must be verified to access workspace
            
        Output:
            - Success message
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Only managers can remove members
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Only workspace owners can remove members.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Cannot remove self
        if id == user.id:
            return Response(
                {
                    'success': False,
                    'message': 'You cannot remove yourself from the workspace.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get the member
        try:
            member = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Member not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if member is in workspace
        try:
            workspace_member = WorkspaceMember.objects.get(
                workspace=workspace,
                user=member
            )
        except WorkspaceMember.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'This user is not a member of your workspace.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # === CLEANUP: Expire all invitations for this member ===
        # This ensures clean state for potential re-invitation
        member_email = member.email
        
        # Expire ALL invitations for this user in this workspace
        # (both pending and accepted - to allow re-invitation after removal)
        Invitation.objects.filter(
            invited_email=member_email,
            workspace=workspace,
            status__in=['pending', 'accepted']
        ).update(status='expired')
        
        # Remove member (only WorkspaceMember, NOT the User object)
        workspace_member.delete()
        
        logger.info(f"Member {member.email} removed from workspace {workspace.id} by {user.email}")
        
        return Response(
            {
                'success': True,
                'message': 'Member removed from workspace successfully.'
            },
            status=status.HTTP_200_OK
        )


class MemberSuspendView(APIView):
    """
    API endpoint for suspending a member (R12).
    
    PUT /workspace/member/<id>/suspend/
    
    Only Manager can suspend members.
    """
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def put(self, request, id):
        """
        Suspend a workspace member.
        
        Business Rules:
            - Only manager can suspend
            - Cannot suspend self
            - Cannot suspend another manager
            - Sets is_active = False
            - User must be verified to access workspace
            
        Output:
            - Success message
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        from .serializers import MemberSuspendSerializer
        
        serializer = MemberSuspendSerializer(
            data={},
            context={'request': request, 'member_id': id}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            member = serializer.validated_data['member']
            
            # Suspend member - update both User and WorkspaceMember
            member.is_active = False
            member.save()
            
            # Also update WorkspaceMember status
            workspace = Workspace.objects.get(owner=request.user)
            try:
                workspace_member = WorkspaceMember.objects.get(
                    workspace=workspace,
                    user=member
                )
                workspace_member.status = 'suspended'
                workspace_member.save()
            except WorkspaceMember.DoesNotExist:
                pass
            
            logger.info(f"Member {member.email} suspended by {request.user.email}")
            
            return Response(
                {
                    'success': True,
                    'message': 'Member suspended successfully.'
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            if isinstance(e.detail, dict):
                error_message = str(list(e.detail.values())[0][0])
            elif isinstance(e.detail, list):
                error_message = str(e.detail[0])
            else:
                error_message = str(e.detail)
            
            return Response(
                {
                    'success': False,
                    'message': error_message
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        except Exception as e:
            logger.error(f"Error suspending member {id} by {request.user.email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while suspending member'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MemberUnsuspendView(APIView):
    """
    API endpoint for unsuspending a member.
    
    PUT /workspace/member/<id>/unsuspend/
    
    Only Manager can unsuspend members.
    """
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def put(self, request, id):
        """
        Unsuspend a workspace member.
        
        Business Rules:
            - Only manager can unsuspend
            - Member must be suspended
            - User must be verified to access workspace
            
        Output:
            - Success message
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Only managers can unsuspend members
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Only workspace owners can unsuspend members.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get the member
        try:
            member = User.objects.get(id=id)
        except User.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Member not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if member is in workspace
        try:
            workspace_member = WorkspaceMember.objects.get(
                workspace=workspace,
                user=member
            )
        except WorkspaceMember.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'This user is not a member of your workspace.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Unsuspend member
        member.is_active = True
        member.save()
        
        workspace_member.status = 'active'
        workspace_member.save()
        
        logger.info(f"Member {member.email} unsuspended by {request.user.email}")
        
        return Response(
            {
                'success': True,
                'message': 'Member unsuspended successfully.'
            },
            status=status.HTTP_200_OK
        )


class RemovePendingInvitationView(APIView):
    """
    API endpoint for removing pending invitations.
    
    DELETE /workspace/invitation/<email>/
    
    Only Manager can remove pending invitations.
    """
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def delete(self, request, email):
        """
        Remove a pending invitation by email.
        
        Business Rules:
            - Only manager can remove invitations
            - Can only remove pending invitations
            - User must be verified to access workspace
            
        Output:
            - Success message
        """
        user = request.user
        
        # Check if user is verified
        if not user.is_verified:
            return Response(
                {
                    'success': False,
                    'message': 'Please verify your email before accessing workspace features.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Only managers can remove invitations
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Only workspace owners can remove invitations.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Find and remove the invitation and workspace member
        try:
            email_lower = email.lower()
            found_something = False
            
            # Remove from WorkspaceMember (only pending entries)
            workspace_members_deleted = WorkspaceMember.objects.filter(
                workspace=workspace,
                invited_email=email_lower,
                status__in=['pending_registration', 'pending_acceptance']
            ).delete()[0]
            
            if workspace_members_deleted > 0:
                found_something = True
            
            # Expire all pending invitations for this email
            invitations_expired = Invitation.objects.filter(
                workspace=workspace,
                invited_email=email_lower,
                status='pending'
            ).update(status='expired')
            
            if invitations_expired > 0:
                found_something = True
            
            if not found_something:
                return Response(
                    {
                        'success': False,
                        'message': 'No pending invitation found for this email.'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            logger.info(f"Pending invitation removed for {email} by {user.email}")
            
            return Response(
                {
                    'success': True,
                    'message': 'Invitation removed successfully.'
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"Error removing invitation for {email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while removing invitation.'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AcceptInvitationView(APIView):
    """
    API endpoint for accepting workspace invitation (R13).
    
    GET /workspace/accept-invite/?token=<token>
    
    Anyone with valid token can accept.
    """
    permission_classes = []  # No authentication required
    
    @transaction.atomic
    def get(self, request):
        """
        Accept workspace invitation using token.
        
        Business Rules:
            - Verifies token (48-hour expiration)
            - If user exists: update WorkspaceMember status to 'active'
            - If user doesn't exist: return invitation info for signup redirect
            - Updates invitation status to 'accepted' when user accepts
            
        Output:
            - Success message (if user exists)
            - Invitation info for signup (if user doesn't exist)
            - Workspace info
        """
        from .serializers import AcceptInvitationSerializer
        
        token = request.query_params.get('token')
        
        if not token:
            return Response(
                {
                    'success': False,
                    'message': 'Invitation token is required.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = AcceptInvitationSerializer(
            data={'token': token}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            invitation = serializer.validated_data['invitation']
            workspace = serializer.validated_data['workspace']
            user = serializer.validated_data['user']
            user_exists = serializer.validated_data['user_exists']
            invited_email = serializer.validated_data['invited_email']
            role = serializer.validated_data['role']
            
            if user_exists:
                # === CASE A: User has existing account ===
                # Auto-add to workspace and tell frontend to redirect to LOGIN
                
                # Get or create WorkspaceMember entry
                workspace_member, created = WorkspaceMember.objects.get_or_create(
                    workspace=workspace,
                    user=user,
                    defaults={
                        'invited_email': invited_email,
                        'role': role,
                        'status': 'active',
                        'joined_at': timezone.now()
                    }
                )
                
                # If already exists but not active, update it
                if not created:
                    workspace_member.status = 'active'
                    workspace_member.role = role
                    workspace_member.joined_at = timezone.now()
                    workspace_member.save()
                
                # Update user role to invited role if different
                if user.role != role:
                    user.role = role
                    user.save()
                
                # Mark invitation as accepted
                invitation.status = 'accepted'
                invitation.save()

                notification_client = get_notification_client()
                owner_email = workspace.owner.email if workspace and workspace.owner else None
                owner_name = workspace.owner.name if workspace and workspace.owner else None
                notification_result = notification_client.send_event(
                    event_type='workspace_member_joined',
                    event_key=f"workspace-join:{workspace.id}:{user.id}",
                    payload={
                        'workspace_id': workspace.id,
                        'workspace_name': workspace.name,
                        'owner_email': owner_email,
                        'owner_name': owner_name,
                        'recipient_emails': [owner_email] if owner_email else [],
                        'joined_user_id': user.id,
                        'joined_user_name': user.name,
                        'joined_user_email': user.email,
                        'joined_role': role,
                    },
                )
                if not notification_result.get('success'):
                    logger.warning(
                        "workspace_member_joined notification dispatch failed workspace=%s user=%s error=%s",
                        workspace.id,
                        user.id,
                        notification_result.get('error'),
                    )
                
                logger.info(f"User {user.email} accepted invitation to workspace {workspace.id}")
                
                # Return response indicating user should log in
                return Response(
                    {
                        'success': True,
                        'need_login': True,
                        'email': invited_email,
                        'message': 'Invitation accepted! Please log in to access the workspace.',
                        'workspace': {
                            'id': workspace.id,
                            'name': workspace.name
                        }
                    },
                    status=status.HTTP_200_OK
                )
            else:
                # === CASE B: User doesn't have an account ===
                # Tell frontend to redirect to registration
                logger.info(f"Invitation for {invited_email} requires signup")
                
                return Response(
                    {
                        'success': True,
                        'need_register': True,
                        'email': invited_email,
                        'role': role,
                        'invitation_token': token,
                        'message': 'Please create an account to accept this invitation.',
                        'workspace': {
                            'id': workspace.id,
                            'name': workspace.name
                        }
                    },
                    status=status.HTTP_200_OK
                )
            
        except serializers.ValidationError as e:
            if isinstance(e.detail, dict):
                error_message = str(list(e.detail.values())[0][0])
            elif isinstance(e.detail, list):
                error_message = str(e.detail[0])
            else:
                error_message = str(e.detail)
            
            return Response(
                {
                    'success': False,
                    'message': error_message
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(f"Error accepting invitation: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while accepting invitation'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminWorkspaceListView(APIView):
    """
    Admin API for global workspace management.

    GET /admin/workspaces/
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        workspaces = Workspace.objects.select_related('owner').all().order_by('-created_at')
        payload = []
        for workspace in workspaces:
            payload.append(
                {
                    'id': workspace.id,
                    'name': workspace.name,
                    'description': workspace.description,
                    'company_number': workspace.company_number,
                    'company_address': workspace.company_address,
                    'created_at': workspace.created_at,
                    'owner': {
                        'id': workspace.owner.id,
                        'name': workspace.owner.name,
                        'email': workspace.owner.email,
                    },
                    'active_members_count': WorkspaceMember.objects.filter(
                        workspace=workspace,
                        status='active',
                    ).count(),
                    'pending_members_count': WorkspaceMember.objects.filter(
                        workspace=workspace,
                        status__in=['pending_registration', 'pending_acceptance'],
                    ).count(),
                }
            )

        return Response(
            {
                'success': True,
                'count': len(payload),
                'workspaces': payload,
            },
            status=status.HTTP_200_OK,
        )


class AdminWorkspaceDetailView(APIView):
    """
    Admin API for workspace details and deletion.

    GET /admin/workspaces/<workspace_id>/
    DELETE /admin/workspaces/<workspace_id>/
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, workspace_id):
        try:
            workspace = Workspace.objects.select_related('owner').get(id=workspace_id)
        except Workspace.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Workspace not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        members = WorkspaceMember.objects.filter(workspace=workspace).select_related('user')
        member_payload = []
        for member in members:
            member_payload.append(
                {
                    'id': member.user.id if member.user else None,
                    'email': member.invited_email,
                    'name': member.user.name if member.user else None,
                    'role': member.role,
                    'status': member.status,
                }
            )

        return Response(
            {
                'success': True,
                'workspace': {
                    'id': workspace.id,
                    'name': workspace.name,
                    'description': workspace.description,
                    'company_number': workspace.company_number,
                    'company_address': workspace.company_address,
                    'created_at': workspace.created_at,
                    'owner': {
                        'id': workspace.owner.id,
                        'name': workspace.owner.name,
                        'email': workspace.owner.email,
                    },
                    'members': member_payload,
                },
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, workspace_id):
        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Workspace not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        workspace.delete()
        return Response(
            {
                'success': True,
                'message': 'Workspace deleted successfully.',
            },
            status=status.HTTP_200_OK,
        )

