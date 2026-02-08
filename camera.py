import cv2
from ultralytics import YOLO

# Load your trained model
model = YOLO("best.pt")

# Initialize webcam
# '0' is usually the default camera. Change to 1, 2, etc. if you have multiple cameras.
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Could not open webcam.")
    exit()

print("Real-time Detection Started...")
print("Press 'q' to quit.")

while True:
    # Read a frame from the webcam
    ret, frame = cap.read()
    if not ret:
        print("Error: Failed to capture image.")
        break

    # Run YOLO inference on the frame
    # stream=True is more efficient for video
    results = model.predict(source=frame, conf=0.25, show=False, stream=True)

    # Process results and draw on frame
    for r in results:
        annotated_frame = r.plot()  # Get frame with bounding boxes and labels

        # Display the frame
        cv2.imshow("YOLO Real-Time Detection", annotated_frame)

    # Break loop on 'q' key press
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release resources
cap.release()
cv2.destroyAllWindows()
