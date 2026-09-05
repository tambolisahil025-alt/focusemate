from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, ARRAY, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True) # Nullable for Social Auth
    name = Column(String, nullable=False)
    avatar = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    location = Column(String, nullable=True)
    provider = Column(String, default="email")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rooms_owned = relationship("Room", back_populates="owner")
    memberships = relationship("RoomMember", back_populates="user")

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, default="others")
    tags = Column(ARRAY(String), default=[])
    max_members = Column(Integer, default=50)
    owner_id = Column(Integer, ForeignKey("users.id"))
    is_live = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="rooms_owned")
    members = relationship("RoomMember", back_populates="room", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="room", cascade="all, delete-orphan")
    resources = relationship("Resource", back_populates="room", cascade="all, delete-orphan")

class RoomMember(Base):
    __tablename__ = "room_members"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String, default="member") # owner, admin, member
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    room = relationship("Room", back_populates="members")
    user = relationship("User", back_populates="memberships")

class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    code = Column(String, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    members = relationship("CourseMember", back_populates="course", cascade="all, delete-orphan")

class CourseMember(Base):
    __tablename__ = "course_members"
    __table_args__ = (UniqueConstraint("course_id", "user_id", name="uq_course_member"),)

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="student", nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="members")
    user = relationship("User")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Nullable for system messages
    content = Column(Text, nullable=False)
    message_type = Column(String, default="text") # text, system
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    room = relationship("Room", back_populates="messages")
    sender = relationship("User")

class Resource(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    added_by_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    resource_type = Column(String, default="link") # video, pdf, link, note, pyq
    link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    room = relationship("Room", back_populates="resources")

class Friendship(Base):
    __tablename__ = "friendships"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String, default="pending") # pending, accepted
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    notification_type = Column(String) # friend_request, room_invite, system
    title = Column(String)
    body = Column(String, nullable=True)
    is_read = Column(Boolean, default=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = Column(String, nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Invitation(Base):
    __tablename__ = "invitations"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    inviter_id = Column(Integer, ForeignKey("users.id"))
    invitee_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String, default="pending") # pending, accepted, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    notify_friend_requests = Column(Boolean, default=True)
    notify_room_invites = Column(Boolean, default=True)
    notify_messages = Column(Boolean, default=True)
    study_reminders = Column(Boolean, default=True)
    motivational_quotes = Column(Boolean, default=True)
    show_online_status = Column(Boolean, default=True)
    profile_visibility = Column(String, default="public")
    dark_mode = Column(Boolean, default=False)

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subject = Column(String)
    description = Column(Text)
    category = Column(String)
    status = Column(String, default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- NEW: DIRECT MESSAGES MODEL ---
class DirectMessage(Base):
    __tablename__ = "direct_messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    message_type = Column(String, default="text")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)
    

# Meetings and related models
class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    host_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meeting_code = Column(String, nullable=True, unique=True, index=True)
    status = Column(String, default="lobby") # lobby, live, ended
    auto_accept = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)

    participants = relationship("MeetingParticipant", back_populates="meeting", cascade="all, delete-orphan")
    invitations = relationship("MeetingInvitation", back_populates="meeting", cascade="all, delete-orphan")

class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="participant") # host, participant
    status = Column(String, default="pending") # pending, approved, rejected
    joined_at = Column(DateTime(timezone=True), nullable=True)
    left_at = Column(DateTime(timezone=True), nullable=True)
    banned = Column(Boolean, default=False)

    meeting = relationship("Meeting", back_populates="participants")

class MeetingInvitation(Base):
    __tablename__ = "meeting_invitations"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    inviter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    single_use = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    meeting = relationship("Meeting", back_populates="invitations")
    
