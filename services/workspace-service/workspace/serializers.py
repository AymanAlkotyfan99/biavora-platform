from rest_framework import serializers
from .models import Workspace, WorkspaceMember, Invitation
from users.models import User
from django.utils import timezone


class WorkspaceUpdateSerializer(serializers.Serializer):
    """Serializer for updating workspace information (Manager only)."""
    
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    company_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    company_address = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, attrs):
        """Validate that user is the workspace owner."""
        user = self.context['request'].user
        workspace = self.context['workspace']
        
        # Check if user is the workspace owner
        if workspace.owner != user:
            raise serializers.ValidationError(
                "Only the workspace owner can update workspace information."
            )
        
        return attrs
    
    def update(self, instance, validated_data):
        """Update workspace name and descriptive fields."""
        if 'name' in validated_data:
            instance.name = validated_data['name']
        
        if 'description' in validated_data:
            instance.description = validated_data['description']

        if 'company_number' in validated_data:
            instance.company_number = validated_data['company_number']

        if 'company_address' in validated_data:
            instance.company_address = validated_data['company_address']
        
        instance.save()
        return instance


class WorkspaceMemberSerializer(serializers.Serializer):
    """Serializer for workspace member information."""
    
    id = serializers.IntegerField(source='user.id')
    name = serializers.CharField(source='user.name')
    email = serializers.EmailField(source='user.email')
    role = serializers.CharField(source='user.role')
    status = serializers.SerializerMethodField()
    
    def get_status(self, obj):
        """
        Determine member status based on user state.
        
        Returns:
            - "suspended" if is_active = False
            - "pending" if is_verified = False
            - "active" otherwise
        """
        user = obj.user
        
        if not user.is_active:
            return "suspended"
        elif not user.is_verified:
            return "pending"
        else:
            return "active"


class WorkspaceSerializer(serializers.ModelSerializer):
    """Serializer for workspace basic information."""

    owner_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "description",
            "company_number",
            "company_address",
            "created_at",
            "owner_id",
        ]
        read_only_fields = ["id", "created_at", "owner_id"]


class InvitationSerializer(serializers.Serializer):
    """Serializer for workspace invitation (R9)."""
    
    email = serializers.EmailField(required=True)
    role = serializers.ChoiceField(choices=['analyst', 'executive'], required=True)
    
    def validate(self, attrs):
        """Validate invitation request."""
        user = self.context['request'].user
        email = attrs.get('email').lower()
        role = attrs.get('role')
        
        # Get manager's workspace
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            raise serializers.ValidationError(
                "Only workspace owners can send invitations."
            )
        
        # Check if email is already an ACTIVE member of this workspace
        # (This allows re-inviting removed users)
        if WorkspaceMember.objects.filter(
            workspace=workspace,
            invited_email=email,
            status='active'
        ).exists():
            raise serializers.ValidationError(
                "This user is already an active member of your workspace."
            )
        
        # Check if user exists and is already active in workspace by user object
        try:
            existing_user = User.objects.get(email=email)
            if WorkspaceMember.objects.filter(
                workspace=workspace,
                user=existing_user,
                status='active'
            ).exists():
                raise serializers.ValidationError(
                    "This user is already an active member of your workspace."
                )
        except User.DoesNotExist:
            pass
        
        # Check if there's already a VALID pending invitation for this email
        # (Expired invitations are OK)
        if Invitation.objects.filter(
            invited_email=email,
            workspace=workspace,
            status='pending',
            expires_at__gt=timezone.now()
        ).exists():
            raise serializers.ValidationError(
                "An invitation has already been sent to this email address."
            )
        
        # Store workspace for use in view
        attrs['workspace'] = workspace
        attrs['email'] = email  # Store lowercase email
        
        return attrs


class RoleAssignmentSerializer(serializers.Serializer):
    """Serializer for assigning/updating member roles (R10)."""
    
    role = serializers.ChoiceField(
        choices=['manager', 'analyst', 'executive'],
        required=True
    )
    
    def validate(self, attrs):
        """Validate role assignment request."""
        user = self.context['request'].user
        member_id = self.context['member_id']
        new_role = attrs.get('role')
        
        # Get manager's workspace
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            raise serializers.ValidationError(
                "Only workspace owners can assign roles."
            )
        
        # Get the target member
        try:
            # Check if it's the owner themselves
            if member_id == user.id:
                raise serializers.ValidationError(
                    "You cannot change your own role."
                )
            
            # Try to find in WorkspaceMember
            member = User.objects.get(id=member_id)
            
            # Check if member belongs to this workspace
            is_member = WorkspaceMember.objects.filter(
                workspace=workspace,
                user=member
            ).exists()
            
            if not is_member and member != workspace.owner:
                raise serializers.ValidationError(
                    "This user is not a member of your workspace."
                )
            
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        
        # Cannot demote another manager
        if member.role == 'manager' and new_role != 'manager':
            raise serializers.ValidationError(
                "You cannot demote another manager."
            )
        
        # Store member for use in view
        attrs['member'] = member
        attrs['workspace'] = workspace
        
        return attrs


class MemberDetailSerializer(serializers.Serializer):
    """Serializer for member detail view (R11)."""
    
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.CharField()
    status = serializers.SerializerMethodField()
    
    def get_status(self, obj):
        """Determine member status."""
        if not obj.is_active:
            return "suspended"
        elif not obj.is_verified:
            return "pending"
        else:
            return "active"


class MemberUpdateSerializer(serializers.Serializer):
    """Serializer for updating member status (R11)."""
    
    status = serializers.ChoiceField(
        choices=['active', 'pending'],
        required=False
    )
    
    def validate(self, attrs):
        """Validate member update request."""
        user = self.context['request'].user
        member_id = self.context['member_id']
        
        # Get manager's workspace
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            raise serializers.ValidationError(
                "Only workspace owners can update members."
            )
        
        # Get target member
        try:
            member = User.objects.get(id=member_id)
            
            # Check if member belongs to workspace
            is_member = WorkspaceMember.objects.filter(
                workspace=workspace,
                user=member
            ).exists()
            
            if not is_member and member != workspace.owner:
                raise serializers.ValidationError(
                    "This user is not a member of your workspace."
                )
            
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        
        attrs['member'] = member
        attrs['workspace'] = workspace
        
        return attrs


class MemberSuspendSerializer(serializers.Serializer):
    """Serializer for suspending a member (R12)."""
    
    def validate(self, attrs):
        """Validate member suspension request."""
        user = self.context['request'].user
        member_id = self.context['member_id']
        
        # Get manager's workspace
        try:
            workspace = Workspace.objects.get(owner=user)
        except Workspace.DoesNotExist:
            raise serializers.ValidationError(
                "Only workspace owners can suspend members."
            )
        
        # Get target member
        try:
            member = User.objects.get(id=member_id)
            
            # Cannot suspend self
            if member_id == user.id:
                raise serializers.ValidationError(
                    "You cannot suspend yourself."
                )
            
            # Cannot suspend another manager
            if member.role == 'manager':
                raise serializers.ValidationError(
                    "You cannot suspend another manager."
                )
            
            # Check if member belongs to workspace
            is_member = WorkspaceMember.objects.filter(
                workspace=workspace,
                user=member
            ).exists()
            
            if not is_member:
                raise serializers.ValidationError(
                    "This user is not a member of your workspace."
                )
            
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        
        attrs['member'] = member
        attrs['workspace'] = workspace
        
        return attrs


class AcceptInvitationSerializer(serializers.Serializer):
    """Serializer for accepting workspace invitation (R13)."""
    
    token = serializers.CharField(required=True)
    
    def validate(self, attrs):
        """
        Validate invitation token by looking up directly in Invitation model.
        
        This is DIFFERENT from email verification tokens!
        Invitation tokens are simple UUIDs stored in Invitation.token field.
        """
        token = attrs.get('token')
        
        # Lookup invitation directly by token (NOT using TimestampSigner!)
        try:
            invitation = Invitation.objects.get(token=token)
        except Invitation.DoesNotExist:
            raise serializers.ValidationError("Invalid invitation link.")
        
        # Check invitation status
        if invitation.status == 'accepted':
            raise serializers.ValidationError("This invitation has already been used.")
        
        if invitation.status == 'expired':
            raise serializers.ValidationError("Invitation link has expired.")
        
        # Check if invitation has expired (48 hours)
        if invitation.is_expired():
            invitation.status = 'expired'
            invitation.save()
            raise serializers.ValidationError("Invitation link has expired.")
        
        # Get workspace
        workspace = invitation.workspace
        invited_email = invitation.invited_email
        role = invitation.role
        
        # Check if user exists
        try:
            user = User.objects.get(email=invited_email)
            user_exists = True
            
            # Check if already an active member
            existing_membership = WorkspaceMember.objects.filter(
                workspace=workspace,
                user=user,
                status='active'
            ).first()
            
            if existing_membership:
                # User is already active - allow them to proceed to login
                pass
                
        except User.DoesNotExist:
            user = None
            user_exists = False
        
        attrs['invitation'] = invitation
        attrs['workspace'] = workspace
        attrs['user'] = user
        attrs['user_exists'] = user_exists
        attrs['invited_email'] = invited_email
        attrs['role'] = role
        
        return attrs

