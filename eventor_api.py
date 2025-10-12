import requests
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Dict, Optional, Union
import logging
import xml.etree.ElementTree as ET

class EventorAPI:
    """Helper class for interacting with the Eventor API."""
    
    BASE_URL = "https://eventor.orienteering.asn.au/api"
    
    # Discipline ID to name mapping
    DISCIPLINE_MAP = {
        '1': 'Foot',
        '2': 'MTBO', 
        '6': 'Park/Street',
    }
    
    # Event Classification ID to name mapping
    CLASSIFICATION_MAP = {
        '1': 'Championship',
        '2': 'National',
        '3': 'State',
        '4': 'Local',
        '5': 'Club',
        '6': 'International',
    }
    
    def __init__(self, api_key: str):
        """Initialize the API helper with your API key."""
        self.api_key = api_key
        self.headers = {
            'ApiKey': api_key
        }
    
    def get_discipline_name(self, discipline_id: str) -> str:
        """Get discipline name from discipline ID."""
        return self.DISCIPLINE_MAP.get(discipline_id, 'Discipline {}'.format(discipline_id))
    
    def get_classification_name(self, classification_id: str) -> str:
        """Get event classification name from classification ID."""
        return self.CLASSIFICATION_MAP.get(classification_id, 'Classification {}'.format(classification_id))
        
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> ET.Element:
        """Make a request to the Eventor API and return the XML data as an ElementTree. If XML parsing fails, log the error and return None."""
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            try:
                return ET.fromstring(response.text)
            except ET.ParseError as e:
                logging.error(f"XMLParseError: {e}. Response text: {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"API request failed: {e}")
            raise
            
    def get_events(self, from_date: Optional[str] = None, 
                   to_date: Optional[str] = None,
                   classification_ids: Optional[List[int]] = None,
                   organisation_ids: Optional[List[int]] = None) -> Dict:
        """
        Get events within a date range.
        
        Args:
            from_date: Start date in format 'YYYY-MM-DD'
            to_date: End date in format 'YYYY-MM-DD'
            classification_ids: List of event classification IDs
                1=championship, 2=national, 3=state, 4=local, 5=club, 6=international
            organisation_ids: Comma-separated list of organisation IDs for the organising clubs. 
                If a state's organisation ID is specified, all events organised by a club in that state will be included. 
                Omit to include all events.
        """
        params = {}
        if from_date:
            params['fromDate'] = f"{from_date} 00:00:00"
        if to_date:
            params['toDate'] = f"{to_date} 23:59:59"
        if classification_ids:
            params['classificationIds'] = ','.join(map(str, classification_ids))
        if organisation_ids:
            params['organisationIds'] = ','.join(map(str, organisation_ids))
            
        return self._make_request('events', params)

    def events_to_dataframe(self, events_data: ET.Element) -> pd.DataFrame:
        """Convert events API response to a pandas DataFrame."""
        events = []
        if events_data is None:
            return pd.DataFrame()
            
        for event in events_data.findall('.//Event'):
            # Extracting the main event details
            event_dict = {
                'EventId': event.findtext('EventId'),
                'Name': event.findtext('Name'),
                'StartDate': event.findtext('StartDate/Date'),
                'StartClock': event.findtext('StartDate/Clock'),
                'FinishDate': event.findtext('FinishDate/Date'),
                'FinishClock': event.findtext('FinishDate/Clock'),
                'EventClassificationId': event.findtext('EventClassificationId'),
                'EventStatusId': event.findtext('EventStatusId'),
                'OrganisationId': event.find('.//Organiser/OrganisationId').text if event.find('.//Organiser') is not None else None,
                'WebURL': event.findtext('WebURL'),
                'PunchingUnitType': event.find('PunchingUnitType').get('value') if event.find('PunchingUnitType') is not None else None,
                'DisciplineIds': ', '.join([d.text for d in event.findall('.//DisciplineId')]),  # Concatenate DisciplineIds
            }

            # Extracting EventRace details
            event_race = event.find('.//EventRace')
            if event_race is not None:
                event_dict['EventRaceDistance'] = event_race.get('raceDistance')
                event_dict['EventRaceId'] = event_race.findtext('EventRaceId')
                event_dict['EventRaceName'] = event_race.findtext('Name') or ''  # Handle empty name
                race_date = event_race.find('RaceDate')
                if race_date is not None:
                    event_dict['RaceDate'] = race_date.findtext('Date')
                    event_dict['RaceClock'] = race_date.findtext('Clock')
                else:
                    event_dict['RaceDate'] = None
                    event_dict['RaceClock'] = None

                # Extracting EventCenterPosition details
                event_center = event_race.find('.//EventCenterPosition')
                if event_center is not None:
                    event_dict['EventCenterX'] = event_center.get('x')
                    event_dict['EventCenterY'] = event_center.get('y')
                    event_dict['EventCenterUnit'] = event_center.get('unit')
                else:
                    event_dict['EventCenterX'] = None
                    event_dict['EventCenterY'] = None
                    event_dict['EventCenterUnit'] = None
            else:
                event_dict['EventRaceId'] = None
                event_dict['EventRaceName'] = ''
                event_dict['RaceDate'] = None
                event_dict['RaceClock'] = None
                event_dict['EventCenterX'] = None
                event_dict['EventCenterY'] = None
                event_dict['EventCenterUnit'] = None

            events.append(event_dict)
        return pd.DataFrame(events)
    
    def get_organizations(self) -> Dict:
        """Get list of all organizations."""
        return self._make_request('organisations')
    
    def organizations_to_dataframe(self, organizations_data: ET.Element) -> pd.DataFrame:
        
        data = []
        
        for org in organizations_data.findall('.//Organisation'):
            org_dict = {
                'OrganisationId': org.findtext('OrganisationId'),
                'Name': org.findtext('Name'),
                'ShortName': org.findtext('ShortName'),
                'MediaName': org.findtext('MediaName'),
                'OrganisationTypeId': org.findtext('OrganisationTypeId'),
                'CountryId': org.find('.//Country/CountryId').get('value') if org.find('.//Country/CountryId') is not None else None,
                'Alpha3': org.find('.//Country/Alpha3').get('value') if org.find('.//Country/Alpha3') is not None else None,
                'CountryName_en': org.find('.//Country/Name[@languageId="en"]').text if org.find('.//Country/Name[@languageId="en"]') is not None else None,
                'CountryName_sv': org.find('.//Country/Name[@languageId="sv"]').text if org.find('.//Country/Name[@languageId="sv"]') is not None else None,
                'Address_careOf': org.find('.//Address').get('careOf') if org.find('.//Address') is not None else None,
                'Address_street': org.find('.//Address').get('street') if org.find('.//Address') is not None else None,
                'Address_city': org.find('.//Address').get('city') if org.find('.//Address') is not None else None,
                'Address_zipCode': org.find('.//Address').get('zipCode') if org.find('.//Address') is not None else None,
                'AddressType': org.find('.//AddressType').get('value') if org.find('.//AddressType') is not None else None,
                'Tele_phoneNumber': org.find('.//Tele').get('phoneNumber') if org.find('.//Tele') is not None else None,
                'Tele_mobilePhoneNumber': org.find('.//Tele').get('mobilePhoneNumber') if org.find('.//Tele') is not None else None,
                'Tele_mailAddress': org.find('.//Tele').get('mailAddress') if org.find('.//Tele') is not None else None,
                'TeleType': org.find('.//TeleType').get('value') if org.find('.//TeleType') is not None else None,
                'ParentOrganisationId': org.find('.//ParentOrganisation/OrganisationId').text if org.find('.//ParentOrganisation/OrganisationId') is not None else None,
                'OrganisationStatusId': org.findtext('OrganisationStatusId'),
                'ModifyDate': org.find('.//ModifyDate/Date').text if org.find('.//ModifyDate/Date') is not None else None,
                'ModifyClock': org.find('.//ModifyDate/Clock').text if org.find('.//ModifyDate/Clock') is not None else None,
            }
            data.append(org_dict)
        
        return pd.DataFrame(data)
    
    def get_event_classes(self, event_id: int, include_entry_fees: bool = True) -> Dict:
        """Get all classes in an event."""
        params = {
            'eventId': event_id,
            'includeEntryFees': include_entry_fees
        }
        return self._make_request('eventclasses', params)
    
    def event_classes_to_dataframe(self, event_classes_data: ET.Element) -> pd.DataFrame:
        
        data = []
    
        for event_class in event_classes_data.findall('.//EventClass'):
            event_class_dict = {
                'EventClassId': event_class.findtext('EventClassId'),
                'Name': event_class.findtext('Name'),
                'ClassShortName': event_class.findtext('ClassShortName'),
                'EventClassStatus': event_class.find('EventClassStatus').get('value') if event_class.find('EventClassStatus') is not None else None,
                'ClassTypeId': event_class.find('.//ClassType/ClassTypeId').text if event_class.find('.//ClassType/ClassTypeId') is not None else None,
                'ClassTypeShortName': event_class.find('.//ClassType/ShortName').text if event_class.find('.//ClassType/ShortName') is not None else None,
                'ClassTypeName': event_class.find('.//ClassType/Name').text if event_class.find('.//ClassType/Name') is not None else None,
                'ExternalId': event_class.findtext('ExternalId'),
                'PunchingUnitType': event_class.find('PunchingUnitType').get('value') if event_class.find('PunchingUnitType') is not None else None,
                'ClassRaceInfoId': event_class.find('.//ClassRaceInfo/ClassRaceInfoId').text if event_class.find('.//ClassRaceInfo/ClassRaceInfoId') is not None else None,
                'EventRaceId': event_class.find('.//ClassRaceInfo/EventRaceId').text if event_class.find('.//ClassRaceInfo/EventRaceId') is not None else None,
                'ClassRaceName': event_class.find('.//ClassRaceInfo/Name').text if event_class.find('.//ClassRaceInfo/Name') is not None else None,
                'ClassRaceStatus': event_class.find('.//ClassRaceInfo/ClassRaceStatus').get('value') if event_class.find('.//ClassRaceInfo/ClassRaceStatus') is not None else None,
                'ClassRacePunchingUnitType': event_class.find('.//ClassRaceInfo/PunchingUnitType').get('value') if event_class.find('.//ClassRaceInfo/PunchingUnitType') is not None else None,
                'MinRunners': event_class.find('.//ClassRaceInfo').get('minRunners') if event_class.find('.//ClassRaceInfo') is not None else None,
                'MaxRunners': event_class.find('.//ClassRaceInfo').get('maxRunners') if event_class.find('.//ClassRaceInfo') is not None else None,
                'NoOfEntries': event_class.find('.//ClassRaceInfo').get('noOfEntries') if event_class.find('.//ClassRaceInfo') is not None else None,
                'NoOfStarts': event_class.find('.//ClassRaceInfo').get('noOfStarts') if event_class.find('.//ClassRaceInfo') is not None else None,
                'Sex': event_class.get('sex'),
                'NumberOfEntries': event_class.get('numberOfEntries')
            }
            data.append(event_class_dict)
    
        return pd.DataFrame(data)
    
    def get_entryfees(self, event_id: int) -> Dict:
        return self._make_request('entryfees/events/' + str(event_id))
    
    def entryfees_to_dataframe(self, entryfees_data: ET.Element) -> pd.DataFrame:
        
        data = []
    
        for entry_fee in entryfees_data.findall('.//EntryFee'):
            entry_fee_dict = {
                'EntryFeeId': entry_fee.findtext('EntryFeeId'),
                'Name': entry_fee.findtext('Name'),
                'Amount': entry_fee.findtext('Amount'),
                'Currency': entry_fee.find('Amount').get('currency') if entry_fee.find('Amount') is not None else None,
                'ExternalFee': entry_fee.findtext('ExternalFee'),
                'FromDateOfBirth': entry_fee.find('.//FromDateOfBirth/Date').text if entry_fee.find('.//FromDateOfBirth/Date') is not None else None,
                'ToDateOfBirth': entry_fee.find('.//ToDateOfBirth/Date').text if entry_fee.find('.//ToDateOfBirth/Date') is not None else None,
                'EntryFeeGroupId': entry_fee.findtext('EntryFeeGroupId'),
                'TaxIncluded': entry_fee.get('taxIncluded'),
                'EntryFeeType': entry_fee.get('entryFeeType'),
                'Type': entry_fee.get('type')
            }
            data.append(entry_fee_dict)
        
        return pd.DataFrame(data)
    
    def get_entries(self, organisation_ids: Optional[List[int]] = None,
                   event_ids: Optional[List[int]] = None,
                   event_class_ids: Optional[List[int]] = None,
                   from_event_date: Optional[str] = None,
                   to_event_date: Optional[str] = None,
                   from_entry_date: Optional[str] = None,
                   to_entry_date: Optional[str] = None,
                   from_modify_date: Optional[str] = None,
                   to_modify_date: Optional[str] = None,
                   include_entry_fees: bool = False,
                   include_person_element: bool = False,
                   include_organisation_element: bool = False,
                   include_event_element: bool = False) -> Dict:
        """
        Get entries based on various parameters.
        
        Args:
            from_date: Start date in format 'YYYY-MM-DD'
            to_date: End date in format 'YYYY-MM-DD'
            classification_ids: List of event classification IDs
                1=championship, 2=national, 3=state, 4=local, 5=club, 6=international
            organisation_ids: List of organisation IDs for the entries.
            event_ids: List of event IDs for the entries.
            event_class_ids: List of event class IDs for the entries.
            from_event_date: Start date for events in format 'YYYY-MM-DD'
            to_event_date: End date for events in format 'YYYY-MM-DD'
            from_entry_date: Start date for entries in format 'YYYY-MM-DD'
            to_entry_date: End date for entries in format 'YYYY-MM-DD'
            from_modify_date: Start date for modified entries in format 'YYYY-MM-DD'
            to_modify_date: End date for modified entries in format 'YYYY-MM-DD'
            include_entry_fees: Set to true to include entry fee information.
            include_person_element: Set to true to include complete person information instead of just a person ID.
            include_organisation_element: Set to true to include complete organisation information instead of just an organisation ID.
            include_event_element: Set to true to include complete event information instead of just an event ID.
        """
        params = {}
        if organisation_ids:
            params['organisationIds'] = ','.join(map(str, organisation_ids))
        if event_ids:
            params['eventIds'] = ','.join(map(str, event_ids))
        if event_class_ids:
            params['eventClassIds'] = ','.join(map(str, event_class_ids))
        if from_event_date:
            params['fromEventDate'] = f"{from_event_date} 00:00:00"
        if to_event_date:
            params['toEventDate'] = f"{to_event_date} 23:59:59"
        if from_entry_date:
            params['fromEntryDate'] = f"{from_entry_date} 00:00:00"
        if to_entry_date:
            params['toEntryDate'] = f"{to_entry_date} 23:59:59"
        if from_modify_date:
            params['fromModifyDate'] = f"{from_modify_date} 00:00:00"
        if to_modify_date:
            params['toModifyDate'] = f"{to_modify_date} 23:59:59"
        params['includeEntryFees'] = include_entry_fees
        params['includePersonElement'] = include_person_element
        params['includeOrganisationElement'] = include_organisation_element
        params['includeEventElement'] = include_event_element

        return self._make_request('entries', params)
    
    def entries_to_dataframe(self, entries_data: ET.Element) -> pd.DataFrame:
        
        data = []
    
        for entry in entries_data.findall('.//Entry'):
            entry_dict = {
                'EntryId': entry.findtext('EntryId'),
                'CompetitorId': entry.find('.//Competitor/CompetitorId').text if entry.find('.//Competitor/CompetitorId') is not None else None,
                'PersonId': entry.find('.//Competitor/PersonId').text if entry.find('.//Competitor/PersonId') is not None else None,
                'OrganisationId': entry.find('.//Competitor/OrganisationId').text if entry.find('.//Competitor/OrganisationId') is not None else None,
                'CCardId': entry.find('.//CCard/CCardId').text if entry.find('.//CCard/CCardId') is not None else None,
                'PunchingUnitType': entry.find('.//CCard/PunchingUnitType').get('value') if entry.find('.//CCard/PunchingUnitType') is not None else None,
                'EventClassId': entry.find('.//EntryClass/EventClassId').text if entry.find('.//EntryClass/EventClassId') is not None else None,
                'EventId': entry.findtext('EventId'),
                'EventRaceId': entry.findtext('EventRaceId'),
                'BibNumber': entry.findtext('BibNumber'),
                'EntryDate': entry.find('.//EntryDate/Date').text if entry.find('.//EntryDate/Date') is not None else None,
                'EntryClock': entry.find('.//EntryDate/Clock').text if entry.find('.//EntryDate/Clock') is not None else None,
                'EntryFeeGroupId': entry.findtext('EntryFeeGroupId'),
                'CreatedBy': entry.find('.//CreatedBy/PersonId').text if entry.find('.//CreatedBy/PersonId') is not None else None,
                'ModifyDate': entry.find('.//ModifyDate/Date').text if entry.find('.//ModifyDate/Date') is not None else None,
                'ModifyClock': entry.find('.//ModifyDate/Clock').text if entry.find('.//ModifyDate/Clock') is not None else None,
                'ModifiedBy': entry.find('.//ModifiedBy/PersonId').text if entry.find('.//ModifiedBy/PersonId') is not None else None,
            }
            data.append(entry_dict)
        
        return pd.DataFrame(data)
    
    def get_competitor_count(self, organisation_ids: Optional[List[int]] = None,
                             event_ids: Optional[List[int]] = None,
                             person_ids: Optional[List[int]] = None) -> Dict:
        """
        Get the competitor count for events based on various parameters.
        
        Args:
            
            organisation_ids: List of organisation IDs for the competitors.
            classification_ids: List of event classification IDs
                1=championship, 2=national, 3=state, 4=local, 5=club, 6=international
            event_ids: list of IDs of the events to get the competitor count for.
            
        """
        params = {}
        if organisation_ids is not None:
            params['organisationIds'] = ','.join(map(str, organisation_ids))
        if event_ids is not None:
            params['eventIds'] = ','.join(map(str, event_ids))
        if person_ids is not None:
            params['personIds'] = ','.join(map(str, person_ids))

        return self._make_request('competitorcount', params)
    
    def competitor_count_to_dataframe(self, competitor_count_data: ET.Element) -> pd.DataFrame:
        
        data = []
    
        for competitor_count in competitor_count_data.findall('.//CompetitorCount'):
            competitor_count_dict = {
                'eventId': competitor_count.get('eventId'),
                'numberOfEntries': competitor_count.get('numberOfEntries'),
                'numberOfStarts': competitor_count.get('numberOfStarts')
            }
            data.append(competitor_count_dict)
        
        return pd.DataFrame(data)
    
    def get_memberships(self, organisation_id: int,
                        year: int,
                        include_child_organisations: bool = False,
                        include_contact_details: bool = False) -> Dict:
        """
        Returns all memberships for an organisation (club) for a specified year.
        
        Args:
            organisation_id: The ID of the organisation. This parameter must be set to the own organisation's ID.
            year: The year to include memberships for.
            include_child_organisations: Set to true to include memberships for any underlying organisations. 
                Not applicable for clubs.
            include_contact_details: Set to true to include contact details for members.
        """
        params = {
            'organisationId': organisation_id,
            'year': year,
            'includeChildOrganisations': include_child_organisations,
            'includeContactDetails': include_contact_details
        }
        
        return self._make_request('memberships', params)
    
    def memberships_to_dataframe(self, memberships_data: ET.Element) -> pd.DataFrame:
        """Convert memberships API response to a pandas DataFrame."""
        data = []
    
        organisation = memberships_data.find('.//Organisation')
        organisation_id = organisation.findtext('Id')
        organisation_name = organisation.findtext('Name')
        organisation_shortname = organisation.findtext('ShortName')
        
        for membership in memberships_data.findall('.//Membership'):
            membership_dict = {
                'OrganisationId': organisation_id,
                'OrganisationName': organisation_name,
                'OrganisationShortName': organisation_shortname,
                'MembershipId': membership.findtext('Id'),
                'Year': membership.findtext('Year'),
                'TypeId': membership.find('.//Type/Id').text if membership.find('.//Type/Id') is not None else None,
                'TypeName': membership.find('.//Type/Name').text if membership.find('.//Type/Name') is not None else None,
                'PersonId': membership.find('.//Person/Id').text if membership.find('.//Person/Id') is not None else None,
                'FirstName': membership.find('.//Person/FirstName').text if membership.find('.//Person/FirstName') is not None else None,
                'LastName': membership.find('.//Person/LastName').text if membership.find('.//Person/LastName') is not None else None,
                'BirthDate': membership.find('.//Person/BirthDate').text if membership.find('.//Person/BirthDate') is not None else None,
                'Sex': membership.find('.//Person/Sex').text if membership.find('.//Person/Sex') is not None else None,
                'PaidTime': membership.findtext('PaidTime')
            }
            data.append(membership_dict)
        
        return pd.DataFrame(data)
    
    def extract_disciplines_from_events(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> pd.DataFrame:
        """
        Extract unique disciplines from events within a date range.
        
        Args:
            from_date: Optional start date in YYYY-MM-DD format
            to_date: Optional end date in YYYY-MM-DD format
            
        Returns:
            DataFrame containing unique disciplines with their IDs and names
        """
        # Get events data
        events_data = self.get_events(from_date=from_date, to_date=to_date)
        
        # Extract unique disciplines
        disciplines = set()
        for event in events_data.findall('.//Event'):
            discipline_id = event.findtext('DisciplineId')
            if discipline_id:
                discipline_name = self.get_discipline_name(discipline_id)
                disciplines.add((discipline_id, discipline_name))
        
        # Convert to DataFrame
        return pd.DataFrame(list(disciplines), columns=['DisciplineId', 'Name'])
    
    