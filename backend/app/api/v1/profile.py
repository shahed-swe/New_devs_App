from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from typing import Dict, Any, List, Optional
import logging
import os
import uuid
from datetime import datetime
from PIL import Image
import io

from ...core.auth import authenticate_request
from ...models.auth import AuthenticatedUser
from ...models.profile import (
    UserProfile, UserProfileUpdate, UserPreferences, UserPreferencesUpdate,
    NotificationPreference, NotificationPreferenceUpdate, AvatarUploadResponse,
    ProfileResponse
)
from ...database import supabase
from ...services import profile_store
from ...config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
AVATAR_SIZE = (300, 300)  # Max avatar dimensions

# Avatars are stored on local disk and served by the backend at /uploads
AVATAR_DIR = os.path.join("uploads", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

def allowed_file(filename: str) -> bool:
    """Check if the file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def resize_image(image_data: bytes, size: tuple = AVATAR_SIZE) -> bytes:
    """Resize image to specified dimensions while maintaining aspect ratio"""
    try:
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary (for PNG with transparency)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        
        # Resize while maintaining aspect ratio
        image.thumbnail(size, Image.Resampling.LANCZOS)
        
        # Save to bytes
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error resizing image: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file"
        )

def _delete_avatar_files(user_id: str) -> None:
    """Remove any stored avatar files for this user."""
    try:
        for name in os.listdir(AVATAR_DIR):
            if name.startswith(f"{user_id}_avatar_"):
                os.remove(os.path.join(AVATAR_DIR, name))
                logger.info(f"Deleted existing avatar file: {name}")
    except FileNotFoundError:
        pass
    except Exception as delete_error:
        logger.warning(f"Could not delete existing avatar files: {delete_error}")

@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: AuthenticatedUser = Depends(authenticate_request)
):
    """Get current user's profile, preferences, and notification settings"""
    try:
        logger.info(f"User {user.email} is fetching their profile.")
        
        # Create default profile data in case tables don't exist or profile is missing
        now_iso = datetime.utcnow().isoformat()
        # Build safe defaults matching the response models when DB rows are missing
        default_profile = {
            'id': f'synthetic-{user.id}',
            'user_id': user.id,
            'display_name': (user.email.split('@')[0] if user.email else 'User'),
            'bio': None,
            'phone': None,
            'department': None,
            'job_title': None,
            'location': None,
            'timezone': 'UTC',
            'language': 'en',
            'theme': 'light',
            'avatar_url': None,
            'created_at': now_iso,
            'updated_at': now_iso,
        }
        
        default_preferences = {
            'id': f'synthetic-{user.id}',
            'user_id': user.id,
            'notification_email': True,
            'notification_push': True,
            'notification_desktop': True,
            'notification_sound': True,
            'auto_refresh': True,
            'compact_view': False,
            'sidebar_collapsed': False,
            'created_at': now_iso,
            'updated_at': now_iso,
        }
        
        profile = None
        preferences = None
        notification_preferences = []
        unread_count = 0
        
        # Try to get user profile
        try:
            profile_response = supabase.table('user_profiles').select('*').eq('user_id', user.id).execute()
            if profile_response.data:
                profile_data = profile_response.data[0]
                profile = UserProfile(**profile_data)
            else:
                logger.info(f"No profile found for user {user.id}, using default profile")
                profile = UserProfile(**default_profile)
        except Exception as profile_error:
            logger.warning(f"Error accessing user_profiles table for user {user.id}: {profile_error}")
            logger.info(f"Using default profile for user {user.id}")
            profile = UserProfile(**default_profile)
        
        # Try to get user preferences
        try:
            preferences_response = supabase.table('user_preferences').select('*').eq('user_id', user.id).execute()
            if preferences_response.data:
                preferences_data = preferences_response.data[0]
                preferences = UserPreferences(**preferences_data)
            else:
                logger.info(f"No preferences found for user {user.id}, using default preferences")
                preferences = UserPreferences(**default_preferences)
        except Exception as preferences_error:
            logger.warning(f"Error accessing user_preferences table for user {user.id}: {preferences_error}")
            logger.info(f"Using default preferences for user {user.id}")
            preferences = UserPreferences(**default_preferences)
        
        # Try to get notification preferences
        try:
            notification_prefs_response = supabase.table('notification_preferences').select('*').eq('user_id', user.id).execute()
            notification_preferences = [NotificationPreference(**pref) for pref in notification_prefs_response.data]
        except Exception as notif_error:
            logger.warning(f"Error accessing notification_preferences table for user {user.id}: {notif_error}")
            logger.info(f"Using empty notification preferences for user {user.id}")
            notification_preferences = []
        
        # Try to get unread notification count
        try:
            unread_response = supabase.rpc('get_unread_notification_count', {'user_uuid': user.id}).execute()
            data = unread_response.data
            if isinstance(data, list):
                # Handle mock/list response
                unread_count = len(data) if data else 0
            else:
                unread_count = data if data is not None else 0
        except Exception as unread_error:
            logger.warning(f"Error getting unread notification count for user {user.id}: {unread_error}")
            unread_count = 0
        
        logger.info(f"Successfully fetched/created profile for user {user.id}")
        
        return ProfileResponse(
            profile=profile,
            preferences=preferences,
            notification_preferences=notification_preferences,
            unread_count=unread_count
        )
        
    except Exception as e:
        logger.error(f"Error fetching profile for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching profile."
        )

@router.put("", response_model=UserProfile)
async def update_profile(
    profile_update: UserProfileUpdate,
    user: AuthenticatedUser = Depends(authenticate_request)
):
    """Update current user's profile information"""
    try:
        logger.info(f"User {user.email} is updating their profile.")
        
        # Prepare update data (only include non-None values)
        update_data = {}
        for field, value in profile_update.dict(exclude_unset=True).items():
            if value is not None:
                update_data[field] = value
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        # Update profile
        response = supabase.table('user_profiles').update(update_data).eq('user_id', user.id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )
        
        updated_profile = UserProfile(**response.data[0])
        logger.info(f"Successfully updated profile for user {user.id}")
        
        return updated_profile
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating profile."
        )

@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    preferences_update: UserPreferencesUpdate,
    user: AuthenticatedUser = Depends(authenticate_request)
):
    """Update current user's UI and general preferences"""
    try:
        logger.info(f"User {user.email} is updating their preferences.")
        
        # Prepare update data
        update_data = preferences_update.dict(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        # Update preferences
        response = supabase.table('user_preferences').update(update_data).eq('user_id', user.id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preferences not found"
            )
        
        updated_preferences = UserPreferences(**response.data[0])
        logger.info(f"Successfully updated preferences for user {user.id}")
        
        return updated_preferences
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating preferences for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating preferences."
        )

@router.put("/notification-preferences/{category}", response_model=NotificationPreference)
async def update_notification_preference(
    category: str,
    preference_update: NotificationPreferenceUpdate,
    user: AuthenticatedUser = Depends(authenticate_request)
):
    """Update notification preferences for a specific category"""
    try:
        logger.info(f"User {user.email} is updating notification preferences for category {category}.")
        
        # Prepare update data
        update_data = preference_update.dict(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        # Update or create notification preference
        response = supabase.table('notification_preferences').update(update_data).eq('user_id', user.id).eq('category', category).execute()
        
        if not response.data:
            # Create if doesn't exist
            create_data = {
                'user_id': user.id,
                'category': category,
                **update_data
            }
            response = supabase.table('notification_preferences').insert(create_data).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update notification preferences"
            )
        
        updated_preference = NotificationPreference(**response.data[0])
        logger.info(f"Successfully updated notification preferences for user {user.id}, category {category}")
        
        return updated_preference
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating notification preferences for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating notification preferences."
        )

@router.post("/avatar", response_model=AvatarUploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(authenticate_request)
):
    """Upload and set user avatar image"""
    try:
        logger.info(f"User {user.email} is uploading an avatar.")
        
        # Validate file
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file selected"
            )
        
        if not allowed_file(file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        
        # Read and validate file size
        file_content = await file.read()
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
        
        # Resize image
        resized_image = resize_image(file_content)

        # Remove previous avatar files, then store the new one on disk.
        # Always saved as JPEG after processing; uuid suffix busts browser cache.
        _delete_avatar_files(user.id)
        unique_filename = f"{user.id}_avatar_{uuid.uuid4().hex}.jpg"
        file_path = os.path.join(AVATAR_DIR, unique_filename)
        with open(file_path, 'wb') as f:
            f.write(resized_image)

        public_url = f"{settings.backend_url}/uploads/avatars/{unique_filename}"

        # Update user profile with new avatar URL
        try:
            await profile_store.set_avatar_url(user.id, user.email, public_url)
        except Exception as update_error:
            # Clean up stored file if profile update fails
            try:
                os.remove(file_path)
            except OSError:
                pass
            logger.error(f"Failed to update profile with new avatar: {update_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update profile with new avatar"
            )

        logger.info(f"Successfully uploaded avatar for user {user.id}")

        return AvatarUploadResponse(
            avatar_url=public_url,
            message="Avatar uploaded successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading avatar for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while uploading avatar."
        )

@router.delete("/avatar")
async def delete_avatar(
    user: AuthenticatedUser = Depends(authenticate_request)
):
    """Delete user's current avatar"""
    try:
        logger.info(f"User {user.email} is deleting their avatar.")

        # Get current profile to find avatar URL
        profile_data = await profile_store.get_profile(user.id)

        if not profile_data or not profile_data.get('avatar_url'):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No avatar found"
            )

        # Delete files from storage
        _delete_avatar_files(user.id)

        # Update profile to remove avatar URL
        await profile_store.set_avatar_url(user.id, user.email, None)

        logger.info(f"Successfully deleted avatar for user {user.id}")
        
        return {"message": "Avatar deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting avatar for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting avatar."
        )
