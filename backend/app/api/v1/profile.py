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

def _default_profile(user: AuthenticatedUser) -> Dict[str, Any]:
    now_iso = datetime.utcnow().isoformat()
    return {
        'id': f'profile-{user.id}',
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

def _default_preferences(user: AuthenticatedUser) -> Dict[str, Any]:
    now_iso = datetime.utcnow().isoformat()
    return {
        'id': f'prefs-{user.id}',
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

        # Fall back to safe defaults when rows are missing
        try:
            profile_data = await profile_store.get_profile(user.id)
        except Exception as profile_error:
            logger.warning(f"Error reading user_profiles for user {user.id}: {profile_error}")
            profile_data = None
        profile = UserProfile(**(profile_data or _default_profile(user)))

        try:
            preferences_data = await profile_store.get_preferences(user.id)
        except Exception as preferences_error:
            logger.warning(f"Error reading user_preferences for user {user.id}: {preferences_error}")
            preferences_data = None
        preferences = UserPreferences(**(preferences_data or _default_preferences(user)))

        try:
            notification_rows = await profile_store.get_notification_preferences(user.id)
            notification_preferences = [NotificationPreference(**row) for row in notification_rows]
        except Exception as notif_error:
            logger.warning(f"Error reading notification_preferences for user {user.id}: {notif_error}")
            notification_preferences = []

        # Unread notifications are not tracked in this environment
        unread_count = 0

        logger.info(f"Successfully fetched profile for user {user.id}")

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

        updated_row = await profile_store.update_profile(user.id, user.email, update_data)
        updated_profile = UserProfile(**updated_row)
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

        updated_row = await profile_store.update_preferences(user.id, update_data)
        updated_preferences = UserPreferences(**updated_row)
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

        updated_row = await profile_store.update_notification_preference(user.id, category, update_data)
        updated_preference = NotificationPreference(**updated_row)
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
