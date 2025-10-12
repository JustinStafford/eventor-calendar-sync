#!/usr/bin/env python3
"""
Google Calendar integration for Eventor events.
"""

import os
from datetime import datetime, time, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

class GoogleCalendarService:
    """Helper class for interacting with Google Calendar API."""
    
    def __init__(self, credentials_file='credentials.json', token_file='token.json'):
        """
        Initialize the Google Calendar service.
        
        Args:
            credentials_file: Path to Google OAuth2 credentials JSON file
            token_file: Path to store/load OAuth2 token
        """
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Calendar API."""
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Credentials file '{self.credentials_file}' not found. "
                        "Please download it from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())
        
        self.service = build('calendar', 'v3', credentials=creds)
    
    def list_calendars(self):
        """
        List all available calendars.
        
        Returns:
            List of calendar objects with id, summary, and description
        """
        try:
            calendar_list = self.service.calendarList().list().execute()
            calendars = calendar_list.get('items', [])
            
            calendar_info = []
            for calendar in calendars:
                calendar_info.append({
                    'id': calendar['id'],
                    'summary': calendar.get('summary', 'No name'),
                    'description': calendar.get('description', 'No description'),
                    'access_role': calendar.get('accessRole', 'unknown')
                })
            
            return calendar_info
            
        except HttpError as error:
            logging.error(f"An error occurred listing calendars: {error}")
            return []
    
    def create_event(self, event_data, calendar_id):
        """
        Create a calendar event.
        
        Args:
            event_data: Dictionary containing event information
                Required keys: 'summary', 'start_datetime'/'start_date', 'end_datetime'/'end_date'
                Optional keys: 'description', 'location', 'all_day'
            calendar_id: ID of the calendar to create the event in
        
        Returns:
            Created event object or None if failed
        """
        try:
            event = {
                'summary': event_data['summary'],
            }
            
            # Handle all-day events vs timed events
            if event_data.get('all_day', False):
                # All-day event
                event['start'] = {
                    'date': event_data['start_date'].strftime('%Y-%m-%d'),
                }
                event['end'] = {
                    'date': event_data['end_date'].strftime('%Y-%m-%d'),
                }
            else:
                # Timed event
                event['start'] = {
                    'dateTime': event_data['start_datetime'].isoformat(),
                    'timeZone': 'UTC',  # All times are now in UTC
                }
                event['end'] = {
                    'dateTime': event_data['end_datetime'].isoformat(),
                    'timeZone': 'UTC',
                }
            
            # Add optional fields
            if 'description' in event_data:
                event['description'] = event_data['description']
            
            if 'location' in event_data:
                event['location'] = event_data['location']
            
            # Create the event
            created_event = self.service.events().insert(
                calendarId=calendar_id, body=event
            ).execute()
            
            logging.info(f"Event created: {created_event.get('htmlLink')}")
            return created_event
            
        except HttpError as error:
            logging.error(f"An error occurred: {error}")
            return None
    
    def list_events(self, calendar_id, max_results=10, time_min=None):
        """
        List events from a specific calendar.
        
        Args:
            calendar_id: ID of the calendar to list events from
            max_results: Maximum number of events to return
            time_min: Minimum time to start listing from (ISO format)
        
        Returns:
            List of event objects
        """
        try:
            if time_min is None:
                time_min = datetime.utcnow().isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id, 
                timeMin=time_min,
                maxResults=max_results, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return events
            
        except HttpError as error:
            logging.error(f"An error occurred: {error}")
            return []
    
    def list_all_events(self, calendar_id):
        """
        List all events from a specific calendar (including past events).
        
        Args:
            calendar_id: ID of the calendar to list events from
        
        Returns:
            List of all event objects
        """
        try:
            # Get events from a year ago to ensure we get all events
            time_min = (datetime.utcnow() - timedelta(days=365)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id, 
                timeMin=time_min,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return events
            
        except HttpError as error:
            logging.error(f"An error occurred: {error}")
            return []
    
    def delete_events_in_date_range(self, calendar_id, from_date=None, to_date=None):
        """
        Delete events from a specific calendar within a date range.
        
        Args:
            calendar_id: ID of the calendar to delete events from
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
        
        Returns:
            Number of events deleted
        """
        try:
            # Convert date strings to datetime objects for comparison
            if from_date:
                from_datetime = datetime.strptime(from_date, '%Y-%m-%d')
            else:
                from_datetime = datetime.now() - timedelta(days=365)  # Default to 1 year ago
            
            if to_date:
                to_datetime = datetime.strptime(to_date, '%Y-%m-%d')
            else:
                to_datetime = datetime.now() + timedelta(days=365)  # Default to 1 year from now
            
            # Get all events from the calendar
            events = self.list_all_events(calendar_id)
            deleted_count = 0
            
            print(f"Checking {len(events)} events for deletion within date range {from_date} to {to_date}...")
            
            for event in events:
                # Check if event has a start date/time
                start_info = event.get('start', {})
                if not start_info:
                    continue
                
                # Handle both dateTime and date formats
                event_start = None
                if 'dateTime' in start_info:
                    # Event with specific time
                    event_start = datetime.fromisoformat(start_info['dateTime'].replace('Z', '+00:00'))
                elif 'date' in start_info:
                    # All-day event
                    event_start = datetime.strptime(start_info['date'], '%Y-%m-%d')
                
                if event_start is None:
                    continue
                
                # Check if event falls within our date range
                if from_datetime.date() <= event_start.date() <= to_datetime.date():
                    event_id = event['id']
                    try:
                        self.service.events().delete(
                            calendarId=calendar_id, 
                            eventId=event_id
                        ).execute()
                        deleted_count += 1
                        print(f"✓ Deleted: {event.get('summary', 'Untitled Event')} ({event_start.strftime('%Y-%m-%d')})")
                    except HttpError as error:
                        logging.error(f"Failed to delete event {event_id}: {error}")
                        print(f"✗ Failed to delete: {event.get('summary', 'Untitled Event')}")
            
            print(f"Successfully deleted {deleted_count} events within date range")
            return deleted_count
            
        except HttpError as error:
            logging.error(f"An error occurred deleting events: {error}")
            return 0
    
    def delete_event(self, event_id, calendar_id):
        """
        Delete a calendar event.
        
        Args:
            event_id: ID of the event to delete
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.service.events().delete(
                calendarId=calendar_id, 
                eventId=event_id
            ).execute()
            logging.info(f"Event {event_id} deleted successfully")
            return True
            
        except HttpError as error:
            logging.error(f"An error occurred: {error}")
            return False
