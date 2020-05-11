#!/usr/bin/python3

import array, gc, libs.driveAPI as driveAPI, math, os, requests, sys, time

from binascii import crc32
from io import BytesIO
from libs.bar import getpatchedprogress
from PIL import Image
from progress.bar import ShadyBar
from progress.spinner import Spinner
from tabulate import tabulate
from libs.uploadHandler import handle_upload_fragment

progress = getpatchedprogress()

version = "1.0.17"

# Open debugging log for writing
debug_log = open("log.txt", "w")
debug_log.write("Version: " + version + "\n\n")

def print_ascii_logo():
	print("\n            ,,,                         ,,,")
	print("      &@@@@@@@@@@@@@              @@@@@@@@@@@@@@")
	print("    @@@@@@@#    %@@@@@#        @@@@@@@@@@@@@@@@@@@@")
	print("  @@@@@@            #@@@     &@@@@@@@         @@@@@@")
	print(" @@@@@                @@@@  @@@@@@@             @@@@@")
	print(" @@@@                   @@@@@@@@@                @@@@@")
	print("@@@@@                    @@@@@@@                  @@@@")
	print("@@@@@                    @@@@@@                   @@@@#")
	print("@@@@@                   @@@@@@                    @@@@,")
	print("&@@@@                 &@@@@@@@@                  *@@@@")
	print(" @@@@@               @@@@@@@ @@@                 @@@@@")
	print("  @@@@@            *@@@@@@#   @@@               @@@@@")
	print("   @@@@@@#       @@@@@@@@      @@@@#          @@@@@@")
	print("    *@@@@@@@@@@@@@@@@@@          @@@@@@@@%@@@@@@@@")
	print("       #@@@@@@@@@@@@               *@@@@@@@@@@@*\n")
	print("InfiniDrive v" + version + " - An unlimited Google Drive storage solution")
	print("by David Berdik, Steven Myrick, Noah Greenberg\n")

if not os.path.exists('credentials.json'):
	# Print an error message and exit if "credentials.json" is not present.
	print('InfiniDrive could not start because you have not provided a "credentials.json" file.')
	print('Please do so and try again. Instructions for doing this are available in "README.md"')
	print('as well as online at https://github.com/DavidBerdik/InfiniDrive')
elif not os.path.exists('token.pickle'):
	# Display welcome message if "token.pickle" does not exist and complete Drive API authentication.
	print_ascii_logo()
	print("Welcome to InfiniDrive! Please complete account authentication using the following URL.")
	print("You can then run your previous command again.\n")
	driveAPI.get_service()
elif (len(sys.argv) == 3 or len(sys.argv) == 4) and str(sys.argv[1]) == "upload":
	# Get the name to use for the file.
	if len(sys.argv) == 3:
		# Use file path as name
		file_name = str(sys.argv[2])
	else:
		# Use user-specified name
		file_name = str(sys.argv[3])
	
	# Determine if upload is taking place from an HTTP or HTTPS URL.
	urlUpload = False
	if sys.argv[2][0:4].lower() == 'http':
		urlUpload = True
		urlUploadHandle = requests.get(sys.argv[2], stream=True, allow_redirects=True)
	
	# Create Google Drive folder
	driveConnect, dirId = driveAPI.begin_storage(file_name)
	fileSize = -1 # If file is being uploaded from web server and size cannot be retrieved this will stay at -1.
	if urlUpload:
		try:
			fileSize = int(urlUploadHandle.headers.get('content-length'))
		except TypeError:
			pass
		if fileSize == -1:
			# If fileSize is set to -1, set totalFrags to "an unknown number of"
			totalFrags = 'an unknown number of'
	else:
		fileSize = os.stat(sys.argv[2]).st_size
	
	if fileSize != -1:
		totalFrags = math.ceil(fileSize / 10223999)
	print('Upload started. Upload will be composed of ' + str(totalFrags) + ' fragments.\n')
	
	# Set chunk size for reading files to 9.750365257263184MB (10223999 bytes)
	readChunkSizes = 10223999
	
	# Doc number
	docNum = 1

	# Used to keep track of the numbers for fragments that have failed uploads.
	failedFragmentsSet = set()

	# Progress bar
	if fileSize == -1:
		# The file size is unknown
		upBar = Spinner('Uploading... ')
	else:
		# The file size is known
		upBar = ShadyBar('Uploading...', max=totalFrags)
	
	if urlUpload:
		# If the upload is taking place from a URL...		
		# Iterate through remote file until no more data is read.
		for fileBytes in urlUploadHandle.iter_content(chunk_size=readChunkSizes):
			# Advance progress bar
			upBar.next()
			
			# Process the fragment and upload it to Google Drive.
			handle_upload_fragment(driveAPI, fileBytes, driveConnect, dirId, docNum, failedFragmentsSet, debug_log)
			
			# Increment docNum for next Word document.
			docNum = docNum + 1
			
			# Run garbage collection. Hopefully, this will prevent process terminations by the operating system on memory-limited devices such as the Raspberry Pi.
			gc.collect()
	else:
		# If the upload is taking place from a file path...	
		# Get file byte size
		fileSize = os.path.getsize(sys.argv[2])
		
		# Iterate through file in chunks.
		infile = open(str(sys.argv[2]), 'rb')
		
		# Read an initial chunk from the file.
		fileBytes = infile.read(readChunkSizes)
		
		# Keep looping until no more data is read.
		while fileBytes:
			# Advance progress bar
			upBar.next()

			# Process the fragment and upload it to Google Drive.
			handle_upload_fragment(driveAPI, fileBytes, driveConnect, dirId, docNum, failedFragmentsSet, debug_log)

			# Increment docNum for next Word document and read next chunk of data.
			docNum = docNum + 1
			fileBytes = infile.read(readChunkSizes)

			# Run garbage collection. Hopefully, this will prevent process terminations by the operating system on memory-limited devices such as the Raspberry Pi.
			gc.collect()
		
		infile.close()
	
	# For each document number in failedFragmentsSet, check for duplicates and remove any if they are present.
	debug_log.write("----------------------------------------\n")
	debug_log.write("Processing detected corruption...\n")
	for name in failedFragmentsSet:
		# Get duplicates.
		duplicates = driveAPI.get_files_with_name_from_folder(driveAPI.get_service(), dirId, name)
		debug_log.write("	Processing corruption of fragments with name " + str(name) + "\n")
		
		# For tracking if we should check data validity
		checkDataValidity = True
		
		# For each entry in the duplicates array...
		for file in duplicates:
			if checkDataValidity:
				# If we should check data validity, retrieve the file data and compare the CRC32 hashes.
				fileData = bytearray([j for i in list(Image.open(driveAPI.get_image_bytes_from_doc(driveAPI.get_service(), file)).convert('RGB').getdata()) for j in i])
				
				if(file['properties']['crc32'] == hex(crc32(fileData))):
					# If the two hashes are identical, mark for no further validity checks and do not delete the file.
					checkDataValidity = False
					debug_log.write("		Validity check disabled\n")
				else:
					# If the hashes do not match, delete the fragment.
					driveAPI.delete_file(driveAPI.get_service(), file['id'])
					debug_log.write("		Removed corrupt duplicate with ID " + file['id'] + " | checkDataValidity = True\n")
			else:
				# If we should not check data validity, delete the file.
				driveAPI.delete_file(driveAPI.get_service(), file['id'])
				debug_log.write("		Removed corrupt duplicate with ID " + file['id'] + " | checkDataValidity = False\n")
			
	debug_log.write("Processing of detected corruption completed.\n")
	
	upBar.finish()
	
	# If the number of fragments to expect from a file upload is known, verify that the upload is not corrupted.
	if totalFrags != 'an unknown number of':
		print('Verifying upload.')
		foundFrags = len(driveAPI.get_files_list_from_folder(driveAPI.get_service(), dirId))
		if(totalFrags != foundFrags):
			debug_log.write("----------------------------------------\n")
			debug_log.write("InfiniDrive detected upload corruption.\n")
			debug_log.write("Expected Fragments: " + str(totalFrags) + "\n")
			debug_log.write("Actual Fragments  : " + str(foundFrags) + "\n")
			print('InfiniDrive has detected that your upload was corrupted. Please report this issue on the InfiniDrive GitHub issue tracker and upload your "log.txt" file.')
	
	print('Upload complete!')
	print('To download, use the following folder ID: ' + dirId)
elif len(sys.argv) == 2 and str(sys.argv[1]) == "list":
	filesList = driveAPI.list_files(driveAPI.get_service())
	
	if(len(filesList) == 0):
		print('No InfiniDrive uploads found')
	else:
		print(tabulate(filesList, headers=['File Name', 'File ID'], tablefmt="psql"))
elif len(sys.argv) == 4 and str(sys.argv[1]) == "rename":
	# Renames the file with the given ID using the given name.
	try:
		driveAPI.rename_file(driveAPI.get_service(), str(sys.argv[2]), str(sys.argv[3]))
		print('File rename complete.')
	except Exception as e:
		debug_log.write("----------------------------------------\n")
		debug_log.write("File rename failure\n")
		debug_log.write("Old Name: " + str(sys.argv[2]) + "\n")
		debug_log.write("New Name: " + str(sys.argv[3]) + "\n")
		debug_log.write("Error:\n")
		debug_log.write(str(e) + "\n")
		print('An error occurred. Please report this issue on the InfiniDrive GitHub issue tracker and upload your "log.txt" file.')
		print('File rename failed.')
elif len(sys.argv) == 4 and str(sys.argv[1]) == "download":
	# Get a list of the files in the given folder.
	files = driveAPI.get_files_list_from_folder(driveAPI.get_service(), str(sys.argv[2]))
	
	# Open a file at the user-specified path to write the data to
	result = open(str(sys.argv[3]), "wb")
	
	# Download complete print flag
	showDownloadComplete = True
	
	# For all files that are in the list...
	total = len(files)
	count = 1
	downBar = ShadyBar('Downloading...', max=total) # Progress bar
	for file in reversed(files):
		downBar.next()
		
		# Get the RGB pixel values from the image as a list of tuples that we will break up and then convert to a bytestring.
		while True:
			try:
				pixelVals = list(Image.open(driveAPI.get_image_bytes_from_doc(driveAPI.get_service(), file)).convert('RGB').getdata())
			except Exception as e:
				debug_log.write("----------------------------------------\n")
				debug_log.write("Fragment download failure\n")
				debug_log.write("Error:\n")
				debug_log.write(str(e) + "\n")
				continue
			pixelVals = [j for i in pixelVals for j in i]
			if len(pixelVals) == 10224000:
				break
				
		# Compare CRC32 hash stored with document to the CRC32 hash of pixelVals. If they do not match, terminate download and report corruption.
		if('properties' in file and file['properties']['crc32'] != hex(crc32(bytearray(pixelVals)))):
			downBar.finish()
			print("\nError: InfiniDrive has detected that the file upload on Google Drive is corrupted and the download cannot complete.", end="")
			showDownloadComplete = False
			break
		
		pixelVals = array.array('B', pixelVals).tostring().rstrip(b'\x00')[:-1]
		
		# Write the data stored in "pixelVals" to the output file.
		result.write(pixelVals)
		count += 1

		# Run garbage collection. Hopefully, this will prevent process terminations by the operating system on memory-limited devices such as the Raspberry Pi.
		gc.collect()
		
	result.close()
	downBar.finish()
	if showDownloadComplete:
		print('\nDownload complete!')
elif len(sys.argv) >= 3 and str(sys.argv[1]) == "delete":
	if len(sys.argv) == 4 and str(sys.argv[3]) == "force-delete":
		# Force delete confirms the deletion.
		delConfirm = True
	else:
		print('Please type "yes" (without quotes) to confirm your intent to delete this file.')
		print('Type any other value to abort the deletion. - ', end = '')
		if 'yes' == input(''):
			delConfirm = True

	# Repeatedly try deleting the folder until we succeed.
	if delConfirm:
		print('Deleting file.')
		while True:
			try:
				driveAPI.delete_file(driveAPI.get_service(), str(sys.argv[2]))
			except Exception as e:
				if(str(e)[:14] == "<HttpError 404"):
					print('File with ID ' + str(sys.argv[2]) + ' does not exist.')
					break
				print('Deletion failed. Retrying.')
				continue
			else:
				print('File deletion complete.')
				break
	else:
		print('File deletion aborted.')
else:
	print_ascii_logo()
	print("help - Displays this help command.")
	print("upload <file path OR http/https URL> <optional: file name> - Uploads specified file to Google Drive")
	print("list - Lists the names of all InfiniDrive files and their IDs")
	print("rename <file ID> <new file name> - Renames the file with the specified ID to the specified new name")
	print("download <file ID> <file path> - Downloads the contents of the specified file ID to the specified file path")
	print("delete <file ID> <optional flag: force-delete> - Deletes the InfiniDrive file specified by the given ID")

debug_log.write("----------------------------------------\n")
debug_log.write("Normal termination.")