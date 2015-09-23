from sqlalchemy import Column, Integer, String

from zoe_client.state import Base


class UserState(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(128))

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email
        }