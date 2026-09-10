"""Google Workspace integration used by the connected portal.

The real OAuth transport and Gmail/Calendar implementation live together in
chief_of_staff.integrations. Legacy CLI tools still use MockInbox/MockCalendar;
use web/app.py for connected accounts, approvals, and organization isolation.
"""
from chief_of_staff.integrations import GoogleConnector, Transport

__all__ = ['GoogleConnector', 'Transport']
