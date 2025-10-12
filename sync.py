#!/usr/bin/env python3
"""
Script to fetch events from Eventor API and print event names.
Gets events from minus 1 month to plus 12 months from current date.

Orgs:
1 - IOF
2 - OA
5 - ONSW
29 - NCN

Disciplines:
1 - Foot
2 - MTBO
6 - Park/Street

Event Classifications:
1 - Championship
2 - National
3 - State
4 - Local
5 - Club
6 - International

"""

from datetime import datetime, timedelta, time
from eventor_api import EventorAPI
from google_calendar import GoogleCalendarService
from dotenv import load_dotenv
import os
import pytz

# Global settings
DAYS_BACK = 7      # Number of days to look back from today
DAYS_FORWARD = 365  # Number of days to look forward from today
LIST_ONLY = True  # Set to True to only list events without syncing to calendar

# Configuration array - each item represents a sync configuration
SYNC_CONFIGURATIONS = [
    {
        'name': 'Newcastle Foot',
        'organisation_ids': [29],  # NCN
        'discipline_ids': [1],     # Park/Street
        'target_calendar_id': '59a1c2710a7d44a616f22945f86dbaae75dc3c477612da780b9d649e53f0bb77@group.calendar.google.com'
    },
    {
        'name': 'Newcastle Park/Street',
        'organisation_ids': [29],  # NCN
        'discipline_ids': [6],     # Park/Street
        'target_calendar_id': '54b94137f695e4bdb042acc7daa42cc2f9d0714731f7014638c778d3b5c8dcfe@group.calendar.google.com'
    },
    {
        'name': 'Newcastle MTBO',
        'organisation_ids': [29],  # NCN
        'discipline_ids': [2],     # MTBO
        'target_calendar_id': '7302418051eb7f5f61cc4016d58be7f7b926b9f42b418e3e45e659f46bd7f4d1@group.calendar.google.com'
    },
    {
        'name': 'CCN Park/Street',
        'organisation_ids': [23],  # CCN
        'discipline_ids': [1],     # Park/Street
        'target_calendar_id': '2a710eb53932be886ed0c3245672e55071535a5db4d3e2e73e46c761d2c06ead@group.calendar.google.com'
    },
    {
        'name': 'Sydney Summer Series',
        'discipline_ids': [1],     # Foot
        'name_filter': 'Sydney Summer Series',
        'target_calendar_id': 'e8cf6247ac2659b8949b6b3dc3133434b5c9a646a0ef0f7607092132f239c4e8@group.calendar.google.com'
    },
    {
        'name': 'NSW State League',
        'organisation_ids': [5],  # ONSW
        'discipline_ids': [1],     # Foot
        'classification_ids': [3],  # State events only
        'target_calendar_id': '5b058336aa3b657d7c1ad7755f932561dcc5b88bcf838012a59cad0a9df4de4d@group.calendar.google.com'
    },
]

def create_calendar_event(event_data, calendar_service, config):
    """
    Create a Google Calendar event from Eventor event data.
    
    Args:
        event_data: Dictionary containing event information
        calendar_service: GoogleCalendarService instance
        config: Configuration dictionary with target_calendar_id, all_day
    
    Returns:
        Created event object or None if failed
    """
    try:
        # Parse the start date
        start_date_str = event_data['start_date']
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # Check if this should be an all-day event
        is_all_day = config.get('all_day', False)
        
        if is_all_day:
            # For all-day events, use just the date
            calendar_event_data = {
                'summary': event_data['name'],
                'start_date': start_date,
                'end_date': start_date,  # All-day events end on the same date
                'all_day': True
            }
        else:
            # Use Eventor times directly (they are in UTC)
            start_time_str = event_data.get('start_time')
            end_time_str = event_data.get('finish_time')
            
            if start_time_str and end_time_str:
                # Parse Eventor times (UTC)
                start_time = datetime.strptime(start_time_str, '%H:%M:%S').time()
                end_time = datetime.strptime(end_time_str, '%H:%M:%S').time()
                
                # Create UTC datetime objects
                start_datetime = datetime.combine(start_date, start_time)
                end_datetime = datetime.combine(start_date, end_time)
                
                # Handle events that cross midnight (end time is before start time)
                if end_time < start_time:
                    # End time is on the next day
                    end_datetime = end_datetime + timedelta(days=1)
                
                # Set default 3-hour duration if end time is same as start time
                if start_time == end_time:
                    end_datetime = start_datetime + timedelta(hours=3)
            else:
                # No Eventor times available - skip this event
                return None
            
            # Prepare event data for Google Calendar
            calendar_event_data = {
                'summary': event_data['name'],
                'start_datetime': start_datetime,
                'end_datetime': end_datetime,
                'all_day': False
            }
        
        # Add event URL to description if event ID is available
        if event_data.get('event_id'):
            event_url = f"https://eventor.orienteering.asn.au/Events/Show/{event_data['event_id']}"
            calendar_event_data['description'] = f"Eventor Event: {event_url}"
        
        # Add location if coordinates are available
        if event_data['lat'] and event_data['lon']:
            calendar_event_data['location'] = f"{event_data['lat']}, {event_data['lon']}"
        
        # Create the calendar event in the target calendar
        return calendar_service.create_event(calendar_event_data, config['target_calendar_id'])
        
    except Exception as e:
        print(f"Error creating calendar event: {e}")
        return None

def process_configuration(api, config, from_date, to_date):
    """
    Process a single sync configuration.
    
    Args:
        api: EventorAPI instance
        config: Configuration dictionary
        from_date: Start date string
        to_date: End date string
    """
    print(f"Name: {config['name']}")
    if 'organisation_ids' in config:
        print(f"Organizations: {config['organisation_ids']}")
    else:
        print("Organizations: All (no filter)")
    print(f"Disciplines: {config['discipline_ids']}")
    if 'classification_ids' in config:
        classification_names = [api.get_classification_name(str(cid)) for cid in config['classification_ids']]
        print(f"Event Types: {config['classification_ids']} ({', '.join(classification_names)})")
    else:
        print("Event Types: All (no filter)")
    if config.get('all_day', False):
        print("Times: All-day events")
    else:
        print("Times: Use Eventor UTC times")
    if 'name_filter' in config:
        print(f"Name Filter: '{config['name_filter']}'")
    print(f"Calendar: {config['target_calendar_id'][:20]}...")
    print("-" * 50)
    
    try:
        # Get events from the API for this configuration
        organisation_ids = config.get('organisation_ids', None)
        classification_ids = config.get('classification_ids', None)
        events_data = api.get_events(from_date=from_date, to_date=to_date, organisation_ids=organisation_ids, classification_ids=classification_ids)
        
        if events_data is None:
            print("No events data received from API")
            return
        
        # Extract event details
        events = []
        for event in events_data.findall('.//Event'):
            name = event.findtext('Name')
            if name:
                # Check if event discipline matches our filter
                discipline_id = event.findtext('DisciplineId')
                if discipline_id and int(discipline_id) not in config['discipline_ids']:
                    continue  # Skip events that don't match our discipline filter
                
                # Check if event name matches our name filter (if specified)
                if 'name_filter' in config:
                    if config['name_filter'].lower() not in name.lower():
                        continue  # Skip events that don't match our name filter

                # Extract start date/time from Eventor
                start_date = event.findtext('StartDate/Date')
                start_time = event.findtext('StartDate/Clock')
                
                # Extract finish date/time from Eventor
                finish_date = event.findtext('FinishDate/Date')
                finish_time = event.findtext('FinishDate/Clock')
                
                # Filter out events that start at midnight Sydney time
                if start_time and finish_time:
                    # Convert UTC times to Sydney time to check for midnight
                    start_time_obj = datetime.strptime(start_time, '%H:%M:%S').time()
                    start_datetime_naive = datetime.combine(datetime.strptime(start_date, '%Y-%m-%d').date(), start_time_obj)
                    
                    # Convert UTC to Sydney timezone
                    utc_tz = pytz.timezone('UTC')
                    sydney_tz = pytz.timezone('Australia/Sydney')
                    start_datetime_utc = utc_tz.localize(start_datetime_naive)
                    start_datetime_sydney = start_datetime_utc.astimezone(sydney_tz)
                    
                    # Check if Sydney time is midnight
                    if start_datetime_sydney.time().strftime('%H:%M:%S') == '00:00:00':
                        continue  # Skip this event
                
                # Skip events without times
                if not start_time or not finish_time:
                    continue
                
                # Extract location coordinates from EventRace
                event_race = event.find('.//EventRace')
                lat = None
                lon = None
                if event_race is not None:
                    event_center = event_race.find('.//EventCenterPosition')
                    if event_center is not None:
                        lat = event_center.get('y')  # y coordinate is typically latitude
                        lon = event_center.get('x')  # x coordinate is typically longitude
                
                # Extract event ID for URL generation
                event_id = event.findtext('EventId')
                
                # Extract discipline ID and map to name using API
                discipline_id = event.findtext('DisciplineId')
                discipline_name = api.get_discipline_name(discipline_id) if discipline_id else 'N/A'
                
                # Extract classification ID and map to name using API
                classification_id = event.findtext('EventClassificationId')
                classification_name = api.get_classification_name(classification_id) if classification_id else 'N/A'
                
                events.append({
                    'name': name,
                    'event_id': event_id,
                    'start_date': start_date,
                    'start_time': start_time,
                    'finish_date': finish_date,
                    'finish_time': finish_time,
                    'lat': lat,
                    'lon': lon,
                    'disciplines': discipline_name,
                    'classification': classification_name
                })
        
        # Print event details
        if events:
            print(f"Found {len(events)} events:")
            print("-" * 150)
            print("{:<3} {:<35} {:<12} {:<20} {:<20} {:<20} {:<15} {:<12} {:<10}".format('#', 'Event Name', 'Date', 'Eventor Times', 'Calendar Times', 'Location', 'Discipline', 'Type', 'Event ID'))
            print("-" * 180)
            for i, event in enumerate(events, 1):
                date_str = event['start_date']
                eventor_times = f"{event['start_time'] or 'N/A'} - {event['finish_time'] or 'N/A'}"
                if config.get('all_day', False):
                    calendar_times = "All-day"
                else:
                    calendar_times = f"{event['start_time'] or 'N/A'} - {event['finish_time'] or 'N/A'}"
                location_str = "{}, {}".format(event['lat'] or 'N/A', event['lon'] or 'N/A')
                event_id_str = event['event_id'] or 'N/A'
                
                print("{:<3} {:<35} {:<12} {:<20} {:<20} {:<20} {:<15} {:<12} {:<10}".format(i, event['name'], date_str, eventor_times, calendar_times, location_str, event['disciplines'], event['classification'], event_id_str))
            
            # Calendar operations (only if not in list-only mode)
            if not LIST_ONLY:
                # Sync calendar events (delete all, then create new ones)
                print("\n" + "=" * 50)
                print("Syncing Google Calendar events...")
                print("=" * 50)
                
                try:
                    calendar_service = GoogleCalendarService()
                    
                    # Step 1: Delete existing events within the date range from the target calendar
                    print("Step 1: Deleting existing events within date range from target calendar...")
                    print(f"Date range: {from_date} to {to_date}")
                    deleted_count = calendar_service.delete_events_in_date_range(config['target_calendar_id'], from_date, to_date)
                    
                    # Step 2: Create new events
                    print(f"\nStep 2: Creating {len(events)} new events...")
                    created_count = 0
                    
                    for event in events:
                        calendar_event = create_calendar_event(event, calendar_service, config)
                        if calendar_event:
                            created_count += 1
                            print("✓ Created: {}".format(event['name']))
                        else:
                            print("✗ Failed: {}".format(event['name']))
                    
                    print(f"\nSync completed!")
                    print(f"- Deleted: {deleted_count} events within date range")
                    print(f"- Created: {created_count} new events")
                    
                except Exception as cal_error:
                    print("Error with Google Calendar: {}".format(cal_error))
                    print("Make sure you have:")
                    print("1. Downloaded credentials.json from Google Cloud Console")
                    print("2. Enabled Google Calendar API")
                    print("3. Set up OAuth2 credentials")
            else:
                # List-only mode - just show the events without calendar operations
                print("\n" + "=" * 50)
                print("LIST ONLY MODE - No calendar operations performed")
                print("=" * 50)
                print(f"Found {len(events)} events that would be synced to calendar:")
                print(f"Target Calendar: {config['target_calendar_id']}")
                print(f"Date Range: {from_date} to {to_date}")
                if config.get('all_day', False):
                    print("Event Type: All-day events")
                else:
                    print("Times: Use Eventor UTC times")
                print("\nTo enable calendar sync, set LIST_ONLY = False in sync.py")
                
        else:
            print("No events found in the specified date range")
            
    except Exception as e:
        print("Error fetching events: {}".format(e))

def main():
    # Load environment variables from .env file
    load_dotenv()
    
    # Get API key from .env file
    api_key = os.getenv('API_KEY')
    if not api_key:
        print("Error: Please set API_KEY in your .env file")
        print("Create a .env file with: API_KEY=your_api_key_here")
        return
    
    # Initialize the API
    api = EventorAPI(api_key)
    
    # Calculate date range using constants
    today = datetime.now()
    from_date = (today - timedelta(days=DAYS_BACK)).strftime('%Y-%m-%d')
    to_date = (today + timedelta(days=DAYS_FORWARD)).strftime('%Y-%m-%d')
    
    print("Eventor Calendar Sync")
    print("=" * 60)
    print(f"Date Range: {from_date} to {to_date}")
    print(f"Configurations: {len(SYNC_CONFIGURATIONS)}")
    if LIST_ONLY:
        print("Mode: LIST ONLY (no calendar operations)")
    else:
        print("Mode: FULL SYNC (will modify calendars)")
    print("=" * 60)
    
    # Process each configuration
    for i, config in enumerate(SYNC_CONFIGURATIONS, 1):
        print(f"\nConfiguration {i}/{len(SYNC_CONFIGURATIONS)}")
        process_configuration(api, config, from_date, to_date)
    
    print(f"\n{'='*60}")
    print("All configurations processed!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
