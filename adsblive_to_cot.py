# This was a ATAK community script developed by https://github.com/niccellular
# Shout out WildFire and SLAB
import requests
import xml.etree.ElementTree as ET
import argparse
import socket
import datetime
import uuid
import time
import ssl


def json_to_cot(json_data, stale_secs):
    root = ET.Element("event")
    root.set("version", "2.0")
    root.set("uid", str(uuid.uuid3(uuid.NAMESPACE_DNS,json_data.get("hex", ""))))
    cot_time = datetime.datetime.now(datetime.timezone.utc)
    stale = cot_time + datetime.timedelta(seconds=stale_secs)
    root.set("time", cot_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    root.set("start", cot_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    root.set("stale", stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))

    ismil = json_data.get("dbFlags", 0) & 1
    category = json_data.get("category", "").lower()

    if not category:
        return ""

    cot_type = "a"
    if ismil:
        # Label all mil as friendly
        cot_type += "-f"
    else:
        # Label all non-mil as neutral
        cot_type += "-n"

    # https://www.adsbexchange.com/emitter-category-ads-b-do-260b-2-2-3-2-5-2/
    if category[0] == "c":
        # C is for ground
        cot_type += "-G"
        if category == "c1":
            #  Surface vehicle – emergency vehicle
            cot_type += "-U-i"
        if category == "c2":
            #  Surface vehicle – service vehicle
            cot_type += "-E-V"
            if not ismil:
                cot_type += "-C"
    else:
        cot_type += "-A"
        if ismil:
            cot_type += "-M"
        else:
            cot_type += "-C"

        if category == "a7":
            # helicopter
            cot_type += "-H"
        elif category[0] == "a":
            # rest of the A should be set to fixed wing
            cot_type += "-F"
        elif category == "b6":
            # Unmanned aerial vehicle
            cot_type += "-F-q"
        elif category == "b2":
            # Lighter than air
            cot_type += "-L"

    root.set("type", cot_type)
    root.set("how", "m-g")
    detail = ET.SubElement(root, "detail")
    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", json_data.get("hex", "")+"_"+json_data.get("r", ""))
    contact.set("type", json_data.get("t", ""))
    remarks = ET.SubElement(detail, "remarks")
    remarks.set("source", "airplanes.live")
    tmp = ""
    for k, v in json_data.items():
        tmp = tmp + k + ":" + str(v) + ", "
    remarks.text = tmp
    track = ET.SubElement(detail, "track")
    # Fetch the ground speed in knots from the JSON data
    gs_knots = json_data.get("gs", 0)
    # Convert the ground speed to meters per second (1 knot = 0.514444 meters per second)
    gs_mps = float(gs_knots) * 0.514444
    track.set("speed", str(gs_mps))
    track.set("course", str(json_data.get("track", "0")))
    point = ET.SubElement(root, "point")

    point.set("lat", str(json_data.get("lat", "")))
    point.set("lon", str(json_data.get("lon", "")))
    
    # Fetch the barometric altitude in feet from the JSON data
    try:
        alt_baro_feet = float(json_data.get("alt_baro", 0))
    except ValueError:
        # might return "ground"
        alt_baro_feet = 0.0
    
    # Standard sea level pressure in hPa
    standard_sea_level_pressure = 1013.25
    
    # Fetch nav_qnh if available
    nav_qnh = float(json_data.get('nav_qnh', standard_sea_level_pressure))
    
    # Convert barometric altitude to pressure altitude
    pressure_altitude_feet = alt_baro_feet + 1000 * (standard_sea_level_pressure - nav_qnh) / 30
    
    # Convert pressure altitude from feet to meters
    pressure_altitude_meters = pressure_altitude_feet * 0.3048
    
    # Set the converted altitude to the 'hae' attribute
    point.set("hae", str(pressure_altitude_meters))
    
    point.set("ce", "9999999.0")
    point.set("le", "9999999.0")
    return ET.tostring(root, encoding="utf-8").decode("utf-8")


def fetch_json(_url):
    response = requests.get(_url)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-lat", type=float, required=True,
                        help="Centerpoint Latitude")
    parser.add_argument("-lon", type=float, required=True,
                        help="Centerpoint Longitude")
    parser.add_argument('--dest', required=True,
                        help='Destination Hostname or IP Address for Sending CoT')
    parser.add_argument('--port', required=True, type=int,
                        help='Destination Port')
    parser.add_argument('--radius', required=False, type=int, default=25,
                        help='Radius in Nautical Miles')
    parser.add_argument('--rate', required=False, type=int, default=0,
                        help='Rate at which to poll the server in seconds. Setting to 0 will run once and exit')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--udp', required=False, action='store_true', default=False,
                        help='Send packets via UDP')
    group.add_argument('--tcp', required=False, action='store_true', default=False,
                        help='Send packets via TCP')
    group.add_argument('--cert', required=False,
                       help='Path to unencrypted User SSL Certificate')
    args = parser.parse_args()

    url = "https://api.airplanes.live/v2/point/" + str(args.lat) + "/" + str(args.lon) + "/" + str(args.radius)

    if args.rate <= 0:
        stale_period = 60
    else:
        stale_period = args.rate * 2.5

    if args.udp:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    elif args.tcp:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((args.dest, args.port))
    else:
        # Cert
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s = ssl.wrap_socket(sock, certfile=args.cert)
        s.connect((args.dest, args.port))

    while True:
        json_data = fetch_json(url)
        if 'ac' in json_data:
            for aircraft in json_data['ac']:
                cot_xml = json_to_cot(aircraft, stale_period)
                if not cot_xml:
                    continue
                # print(cot_xml)
                if args.udp:
                    s.sendto(bytes(cot_xml, "utf-8"), (args.dest, args.port))
                else:
                    s.sendall(bytes(cot_xml, "utf-8"))
        if args.rate <= 0:
            break
        else:
            time.sleep(args.rate)
