import requests

def check_nhtsa_database(year, make):
    # Official API endpoint to fetch all registered model names for a specific year and brand
    url = f"https://api.nhtsa.gov/products/vehicle/models?modelYear={year}&make={make}&issueType=r"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            results = response.json().get("results", [])
            models = [row.get("ModelName") for row in results if row.get("ModelName")]
            return sorted(list(set(models)))
        else:
            return f"Error: Received status code {response.status_code}"
    except Exception as e:
        return f"Connection Failed: {e}"

if __name__ == "__main__":
    tests = [
        ("2023", "Chevrolet"),
        ("2022", "Hyundai"),
        ("2007", "Blue Bird")
    ]
    
    print("=== STARTING THE COMPLETE API DATABASE BLANKET SCAN ===\n")
    for year, make in tests:
        print(f"Searching all official database records for: {year} {make.upper()}...")
        valid_models = check_nhtsa_database(year, make)
        
        if isinstance(valid_models, list):
            print(f"Found {len(valid_models)} recognized models:")
            for m in valid_models:
                # Look for hints matching our targets
                if any(x in m.upper() for x in ["KONA", "TRAIL", "COMMERCIAL"]):
                    print(f"  >>> [TARGET MATCH] -> '{m}'")
                else:
                    print(f"      '{m}'")
        else:
            print(f"  {valid_models}")
        print("-" * 60)
