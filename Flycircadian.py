import cv2
import csv
import PySimpleGUI as sg
import datetime
import sys
import numpy as np

#TODO Move this to a config file
# Frames not moving before fly is considered asleep, change if environment of camera is noisy
TIMEOUT = 300
# Frequency of progress updates in frames
FRAMES_TO_OUTPUT_PROGRESS = 600


def PartitionGUI(video):
    graph = sg.Graph(canvas_size=(video.stream.get(3), video.stream.get(4)), graph_bottom_left=(0, 0),
                     graph_top_right=(video.stream.get(3), video.stream.get(4)), key="imagearea", enable_events=True,
                     drag_submits=True)

    layout = [
        [sg.Button("Undo"), sg.Button("Finish")],
        [graph]
    ]

    window = sg.Window("Please partition the flies into different boxes:", layout)
    window.Finalize()
    graph.bind("<Leave>", "-LEAVE-")
    ret, frame = video.stream.read()
    if ret:
        name_of_file = datetime.datetime.now().strftime("%m%d%Y%H%M%S") + "temp.png"
        try:
            ret = cv2.imwrite(name_of_file, frame)
        except IOError:
            raise SystemExit("Unable to write initial frame to disk, try deleting older temp files")

        graph.DrawImage(filename=name_of_file, location=(0, int(video.stream.get(4))))

    """
    mouse_being_dragged: Boolean that checks if mouse is being held down
    anchor_coordinates: List that holds coordinates of corners of boxes according to button presses, input to FlyPartition()
    undo_stack: holds references to rectangle objects for undo 
    partition_stack: array containing FlyPartition objects
    """

    mouse_being_dragged = False
    #TODO change coordinates to NamedTuples
    anchor_coordinates = []
    undo_stack = []  # add undo
    partition_stack = FlyPartitionList()
    previous_rect = None

    while True:
        event, values = window.read()
        # print(event)
        # print(values)

        if event == "Finish":
            break

        elif event == sg.WINDOW_CLOSED:
            sys.exit(0)

        elif event == "Undo":
            if undo_stack and partition_stack.plist:
                textrectpair = undo_stack.pop()
                graph.delete_figure(textrectpair[0])
                graph.delete_figure(textrectpair[1])
                partition_stack.plist.pop()

        elif event == "imagearea-LEAVE-" and mouse_being_dragged:
            anchor_coordinates.clear()
            mouse_being_dragged = False
            print("Mouse left the area")

        elif event == "imagearea":
            if not mouse_being_dragged:
                # print("Mouse button press")
                mouse_being_dragged = True
                anchor_coordinates.append(values["imagearea"])

            if mouse_being_dragged:
                graph.DeleteFigure(previous_rect)
                # print("Mouse button drag")
                previous_rect = graph.DrawRectangle(top_left=anchor_coordinates[0], bottom_right=values["imagearea"],
                                                    line_color="red")

        elif event == "imagearea+UP" and mouse_being_dragged:
            mouse_being_dragged = False
            # print("Mouse button release")
            anchor_coordinates.append(values["imagearea"])
            assert (len(anchor_coordinates) == 2)

            #TODO Add code to prevent intersections?
            """
            for rectangle in undo_stack:
                bounds = graph.GetBoundingBox(rectangle)
                
                #Detect intersections of boxes
                if((bounds[0] <= anchor_coordinates[0][0] <= bounds[2] and bounds[1] <= anchor_coordinates[0][1] <= bounds[3]) or (bounds[0]    <= anchorcoordinates[1][0] <= bounds[2] and bounds[1] <= anchorcoordinates[1][1] <= bounds[3])):
                    
            """
            reprompt = True
            while reprompt:
                reprompt = False

                partname = sg.popup_get_text("Please enter a unique label for the fly in the partition:",
                                             default_text="fly",
                                             keep_on_top=True,
                                             modal=True)

                for partition in partition_stack.plist:

                    if partname == partition.name:
                        print("Labels must be unique")
                        reprompt = True

                    elif partname == "":
                        print("Labels cannot be blank")
                        reprompt = True
                    #TODO Make sure None can't be a label, may not be possible
                    elif partname is None:
                        print("Please enter a value")
                        reprompt = True

            undo_stack.append((graph.DrawRectangle(top_left=anchor_coordinates[0],
                                                   bottom_right=anchor_coordinates[1], line_color="green",
                                                   line_width=5),
                               graph.DrawText(location=anchor_coordinates[0], text=partname, color="white")))
            partition_stack.plist.append(FlyPartition(partname, anchor_coordinates, partition_stack))
            anchor_coordinates.clear()

    window.close()
    partition_stack.LargestArea()
    partition_stack.ChangeCoordinates(video.stream.get(4))
    return partition_stack


class VideoStream:
    """
    self.stream: points to VideoCapture object looking at file/camera
    self.framestorun: frames to run program, equal to seconds to run on 1 FPS camera
    """

    def __init__(self):
        # Look for video file with -video arg and camera stream with -camera arg
        try:
            self.stream = cv2.VideoCapture(sys.argv[1])
            if not self.stream.isOpened():
                raise IOError
            self.framestorun = int(sys.argv[2])
            if self.framestorun == "endless":
                print("Running in endless mode.")
            elif type(self.framestorun) is not int:
                raise TypeError
        except IndexError:
            raise SystemExit(f"Usage: {sys.argv[0]} (<PathToFile>|<CameraID>) (int <FramesToRun>)")
        except IOError:
            raise SystemExit("Video/camera capturing failed to initialize")
        except TypeError:
            raise SystemExit("Frames to run and CameraID must be Integers. Path to video file must be String.")
        self.framesprocessed = 0

    def OutputExpectedTime(self):
        expected_time = datetime.timedelta(seconds=self.framestorun * self.stream.get(5))
        print(f"Flycircadian.py will run for {expected_time}")

    def FrameProgress(self):
        timeprocessed = datetime.timedelta(seconds=self.framesprocessed * self.stream.get(5))
        print(f"Flycircadian.py has processed {self.framesprocessed} frames so far or {timeprocessed} of video")

    def CountdownFramesToRun(self, partitions):
        self.framestorun -= 1
        if self.framestorun <= 0:
            partitions.SaveToCsv()
            sys.exit(0)


class FlyPartitionList:
    """
    plist: list containing all FlyPartition objects initialized in Partition UI
    logdata: dicts with names of flys as keys and list containing times when wakeup/asleep, written to csv file periodically
    self.stepsbeforesave: times new values are appended to log before attempting to save to csv
    self.csvname: name of csv file
    self.largestarea: largest FlyPartition.boundbox area used in deleting abberant contours
    self.logmode: 0 if in camera mode, 1 if in video mode
    
    """

    def __init__(self):
        self.plist = []
        self.logdata = {}
        self.stepsbeforesave = 5
        self.csvname = ""
        self.largestarea = 0

        if type(sys.argv[1]) == int:
            self.logmode = 0
        else:
            self.logmode = 1

    def LargestArea(self):
        for partition in self.plist:
            br_point = np.array((partition.boundbox[0][0], partition.boundbox[1][1]))
            vertline = np.linalg.norm(partition.boundbox[0] - br_point)
            horline = np.linalg.norm(partition.boundbox[1] - br_point)
            area = vertline * horline
            if area > self.largestarea:
                self.largestarea = area
        print(self.largestarea)
    
    #Change y coordinate to be compatible with opencv's hipster coordinate system
    def ChangeCoordinates(self, maxy):
        for partition in self.plist:
            partition.boundbox[0][1] = maxy - partition.boundbox[0][1]
            partition.boundbox[1][1] = maxy - partition.boundbox[1][1]
        
    def IsInsideOrOutlier(self, coordinate, streamtime):
        outlier = True
        for partition in self.plist:
            if (partition.boundbox[0][0] <= coordinate[0] <= partition.boundbox[1][0]) and (
                    partition.boundbox[0][1] <= coordinate[1] <= partition.boundbox[1][1]):
                outlier = False
                if partition.awake:
                    partition.ResetTimer()
                else:
                    print("wake up")
                    partition.WakeUp(streamtime)
                    
            elif partition.awake:
                partition.IncSleepTimer(streamtime)

        if outlier:
            self.OutlierLogging(coordinate, streamtime)

    def InitializeLogging(self):
        for partition in self.plist:
            # key is also at beginning of list for easier csv writing
            self.logdata.update({partition.name: [partition.name]})
        self.logdata.update({"outlier": ["outlier"]})

        try:
            self.csvname = sys.argv[3]
        except IndexError:
            print("Name for csv file not found in args, using default name 'Flycircadian.csv' instead")
            self.csvname = "Flycircadian"

    def PartitionLogging(self, partition, streamtime, was_awake):
        if self.logmode == 0:
            currtime = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        else:
            currtime = datetime.timedelta(milliseconds=streamtime)
  
        if was_awake: 
            entry = str(currtime) + " SLEEP"
        else: 
            entry = str(currtime) + " WAKE"
        
        self.logdata[partition.name].append(entry)       
        self.stepsbeforesave -= 1
        if self.stepsbeforesave == 0:
            self.SaveToCSV()

    # TODO Remove OutlierLogging as it overloads memory quickly
    def OutlierLogging(self, coordinate, streamtime):
        if self.logmode == 0:
            currtime = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S ")
        else:
            currtime = datetime.timedelta(milliseconds=streamtime)
        self.logdata["outlier"].append(str(currtime) + str(coordinate))
        self.stepsbeforesave -= 1
        if self.stepsbeforesave == 0:
            self.SaveToCSV()

    def SaveToCSV(self):
        try:
            with open(self.csvname, 'w+', newline='') as csvfile:
                csvwrite = csv.writer(csvfile, dialect='excel')
                for key in self.logdata.keys():
                    csvwrite.writerow(self.logdata[key])
        except IOError:
            print(
                "Program was prevented from writing to csv file, will retry when new values are appended to the log in memory")
        self.stepsbeforesave = 5


class FlyPartition:
    """
    name: label attached to fly in partition
    boundbox: coordinates of box demarcating fly sarea
    awake: whether fly in current partition is awake
    _timer: timer tied to FPS of camera, sets fly as asleep after exceeding TIMEOUT
    partlist: points to FlyPartitionList for logging
    """

    def __init__(self, partname, coordinates, partition_stack):
        self.name = partname
        self.boundbox = np.array(coordinates[:])
        self.awake = True
        self._timer = 0
        self.partlist = partition_stack
        assert (len(self.boundbox) == 2)

    def IncSleepTimer(self, streamtime):
        self._timer += 1
        if self._timer >= TIMEOUT:
            print("help")
            self.ResetTimer()
            self.partlist.PartitionLogging(self, streamtime, self.awake)
            self.awake = False

    # Maybe decrement instead of completely reset if too many false negatives for asleep flies or set TIMEOUT much lower
    def ResetTimer(self):
        print(self._timer)
        self._timer = 0
        
    def WakeUp(self, streamtime):
        if not self.awake:
            self.ResetTimer()
            self.partlist.PartitionLogging(self, streamtime, self.awake)
            self.awake = True


def MotionDetection(video, partitions):
    ret,previous_frame = video.stream.read()
    output_progress_counter = 0

    while True:
        ret, current_frame = video.stream.read()
        if not ret:
            print("OpenCV failed to detect anymore frames. Finishing...")
            break

        #Subtract frames, process, and find curves present in frame
        difference = cv2.absdiff(previous_frame, current_frame)
        thresholdmat = cv2.threshold(difference, 15, 255, cv2.THRESH_BINARY_INV)[1]
        thresholdmat = cv2.cvtColor(thresholdmat, cv2.COLOR_BGR2GRAY)
        contours, hierarchy = cv2.findContours(thresholdmat, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        if len(contours) > 0:
            for c in contours:
                moment = cv2.moments(c)
                #Discard degenerate contours whose areas are too small or larger than partitions
                if moment["m00"] < 4 or moment["m00"] > partitions.largestarea:
                    continue
                else:
                    """
                    Debug visualization code:
                    
                    cv2.drawContours(thresholdmat, contours, -1, (0,255,0), 3)
                    cv2.circle(thresholdmat,(int(moment["m10"] / moment["m00"]), int(moment["m01"] / moment["m00"])), radius = 5, color = (100,100,240), thickness = -1)
                    cv2.imshow("fug", thresholdmat)
                    cv2.waitKey(0)
                    """
                    coordinates = (int(moment["m10"] / moment["m00"]), int(moment["m01"] / moment["m00"]))
                    #TODO CRITICAL: Make sure IncSleepTimer is incremented only once per frame instead of per curve using a bit/list of flags
                    partitions.IsInsideOrOutlier(coordinates, video.stream.get(0))
        
        if video.framestorun != "endless":
            video.CountdownFramesToRun(partitions)

        # If FRAMES_TO_OUTPUT_PROGRESS frames have been processed so far, output progress
        if output_progress_counter == FRAMES_TO_OUTPUT_PROGRESS:
            output_progress_counter = 0
            video.FrameProgress()

        else:
            output_progress_counter += 1

        video.framesprocessed += 1
        previous_frame = current_frame[:]
    return 0


# System args: Flycircadian.py (<PATHTOFILE>|<cameraID>) (int <FramesToRun>) (<CSVFilename> to save to)
def main():
    video = VideoStream()
    partitions = PartitionGUI(video)
    partitions.InitializeLogging()
    if not video.framestorun == "endless":
        video.OutputExpectedTime()
    try:
        MotionDetection(video, partitions)
    except MemoryError:
        raise SystemExit("System ran out of memory, consider lowering fps of camera or allocating more memory")


if __name__ == "__main__":
    main()
