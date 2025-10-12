#!/usr/bin/env python3
"""
Script to fetch organizations from Eventor API and print organization names and IDs.
"""

from eventor_api import EventorAPI
from dotenv import load_dotenv
import os

def get_organizations():
    """Get organizations from Eventor API and print their names and IDs."""
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
    
    print("Fetching organizations from Eventor API...")
    print("=" * 50)
    
    try:
        # Get organizations from the API
        orgs_data = api.get_organizations()
        
        if orgs_data is None:
            print("No organizations data received from API")
            return
        
        # Extract organization names and IDs
        organizations = []
        for org in orgs_data.findall('.//Organisation'):
            org_id = org.findtext('OrganisationId')
            name = org.findtext('Name')
            short_name = org.findtext('ShortName')
            
            if org_id and name:
                organizations.append({
                    'id': org_id,
                    'name': name,
                    'short_name': short_name or ''
                })
        
        # Print organizations
        if organizations:
            print(f"Found {len(organizations)} organizations:")
            print("-" * 80)
            print(f"{'ID':<8} {'Name':<50} {'Short Name':<20}")
            print("-" * 80)
            
            for org in organizations:
                short_name_display = org['short_name'] if org['short_name'] else '-'
                print(f"{org['id']:<8} {org['name']:<50} {short_name_display:<20}")
        else:
            print("No organizations found")
            
    except Exception as e:
        print(f"Error fetching organizations: {e}")

def main():
    """Main function to run the organization fetcher."""
    get_organizations()

if __name__ == "__main__":
    main()
