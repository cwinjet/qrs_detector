import serial
import numpy as np
from scipy.signal import butter, lfilter
from collections import deque
import random


class QRSDetector(object):
    """QRS complex detector."""

    def __init__(self, port, baud_rate, signal_freq):
        """Variables initialization and start reading ECG measurements."""

        # Configuration parameters.
        self.signal_freq_samples_per_sec = signal_freq  # signal frequency
        # TODO: This value should be dynamic when dynamic freq will be implemented.
        self.number_of_samples_stored = 200  # samples
        self.filter_lowcut = 0.0  # band pass filter low cut value
        self.filter_highcut = 15.0  # band pass filter high cut value
        self.filter_order = 1
        # TODO: This value should be dynamic when dynamic freq will be implemented or time based.
        self.integration_window = 15  # signal integration window length in samples
        self.findpeaks_limit = 0.40
        # TODO: This value should be dynamic when dynamic freq will be implemented.
        self.findpeaks_spacing = 50 # samples
        # TODO: This value should be dynamic when dynamic freq will be implemented or time based.
        self.refractory_period = 120  # samples
        # TODO: This value should be dynamic when dynamic freq will be implemented.
        self.detection_window = 40  # samples
        self.signal_peak_filtering_factor = 0.125 # detection and thresholding params
        self.noise_peak_filtering_factor = 0.125 # detection and thresholding params
        self.signal_noise_diff_weight = 0.25 # detection and thresholding params

        # Measured and calculated values.
        self.most_recent_measurements = deque([0], self.number_of_samples_stored)  # most recent measurements array
        # TODO: Could this be time based instead of sample number based? If sample based - need to be dynamic when dynamic freq will be implemented.
        self.time_since_last_detected_qrs = 0  # samples
        self.signal_peak_value = 0.0
        self.noise_peak_value = 0.0
        self.threshold_value = 0.0

        # Run the detector.
        self.connect_to_ecg(port=port, baud_rate=baud_rate)

    # ECG interfacing methods.
    def connect_to_ecg(self, port, baud_rate):
        try:
            serial_port = serial.Serial(port, baud_rate)
            print("Connected! Starting reading ECG measurements.")
        except:
            print("Cannot connect to provided port!")
            return

        while True:
            raw_measurement = serial_port.readline()
            self.process_measurement(raw_measurement=raw_measurement)

    # Data processing methods.
    def process_measurement(self, raw_measurement):
        """Parsing raw data line."""

        raw_measurement_split = raw_measurement.decode().rstrip().split(';')

        if len(raw_measurement_split) != 2:
            return
        try:
            timestamp = float(raw_measurement_split[0])
            measurement = float(raw_measurement_split[1])
        except Exception:
            return

        # Not physiologically possible ECG error measurements rejection.
        if measurement > 10:
            return

        self.most_recent_measurements.append(measurement)
        self.extract_peaks(self.most_recent_measurements)

    def extract_peaks(self, most_recent_measurements):
        """Proceses received data."""

        # Signal filtering - band pass 0-15 Hz.
        filtered_signal = self.bandpass_filter(most_recent_measurements, lowcut=self.filter_lowcut,
                                               highcut=self.filter_highcut, signal_freq=self.signal_freq_samples_per_sec,
                                               filter_order=self.filter_order)

        # Derivative - provides QRS slope info.
        differentiated_signal = np.ediff1d(filtered_signal)

        # Squaring.
        squared_signal = differentiated_signal**2

        # Moving-window integration.
        integrated_signal = np.convolve(squared_signal, np.ones(self.integration_window))

        # Fiducial mark - peak detection on integrated signal.
        detected_peaks_indices = self.findpeaks(integrated_signal, limit=self.findpeaks_limit, spacing=self.findpeaks_spacing)
        detected_peaks_indices = detected_peaks_indices[detected_peaks_indices > self.number_of_samples_stored - self.detection_window]
        detected_peaks_values = integrated_signal[detected_peaks_indices]

        self.detect_qrs(detected_peaks_indices=detected_peaks_indices, detected_peaks_values=detected_peaks_values)

    # Detection methods.
    def detect_qrs(self, detected_peaks_indices, detected_peaks_values):
        """Thresholding detected peaks - integrated - signal."""

        self.time_since_last_detected_qrs += 1

        # After a valid QRS complex detection, there is a 200 ms refractory period before the next one can be detected.
        if self.time_since_last_detected_qrs > self.refractory_period:

            # Check whether any peak was detected in analysed samples window.
            if len(detected_peaks_indices) > 0:

                # Take the last one detected in analysed samples window as the most recent.
                most_recent_peak_idx, most_recent_peak_value = detected_peaks_indices[-1], detected_peaks_values[-1]

                # Peak must be classified as a noise peak or a signal peak. To be a signal peak it must exceed threshold_i_1.
                if most_recent_peak_value > self.threshold_value:
                    self.handle_detection()
                    self.time_since_last_detected_qrs = 0
                    self.signal_peak_value = self.signal_peak_filtering_factor * most_recent_peak_value + (1 - self.signal_peak_filtering_factor) * self.signal_peak_value
                else:
                    self.noise_peak_value = self.noise_peak_filtering_factor * most_recent_peak_value + (1 - self.noise_peak_filtering_factor) * self.noise_peak_value

                self.threshold_value = self.noise_peak_value + self.signal_noise_diff_weight * (self.signal_peak_value - self.noise_peak_value)


    def handle_detection(self):
        print("Pulse")

    # Tools methods.
    def bandpass_filter(self, data, lowcut, highcut, signal_freq, filter_order):
        """Constructs signal filter and uses it to given dataset."""
        nyquist_freq = 0.5 * signal_freq
        low = lowcut / nyquist_freq
        high = highcut / nyquist_freq
        b, a = butter(filter_order, [low, high], btype="band")
        y = lfilter(b, a, data)
        return y

    # Janko SLavic peak detection algorithm and implementation.
    # https://github.com/jankoslavic/py-tools/tree/master/findpeaks
    def findpeaks(self, data, spacing=1, limit=None):
        """Finds peaks in `data` which are of `spacing` width and >=`limit`.
        :param data: values
        :param spacing: minimum spacing to the next peak (should be 1 or more)
        :param limit: peaks should have value greater or equal
        :return:
        """
        len = data.size
        x = np.zeros(len + 2 * spacing)
        x[:spacing] = data[0] - 1.e-6
        x[-spacing:] = data[-1] - 1.e-6
        x[spacing:spacing + len] = data
        peak_candidate = np.zeros(len)
        peak_candidate[:] = True
        for s in range(spacing):
            start = spacing - s - 1
            h_b = x[start: start + len]  # before
            start = spacing
            h_c = x[start: start + len]  # central
            start = spacing + s + 1
            h_a = x[start: start + len]  # after
            peak_candidate = np.logical_and(peak_candidate, np.logical_and(h_c > h_b, h_c > h_a))

        ind = np.argwhere(peak_candidate)
        ind = ind.reshape(ind.size)
        if limit is not None:
            ind = ind[data[ind] > limit]
        return ind


if __name__ == "__main__":
    qrs_detector = QRSDetector(port="/dev/cu.usbmodem14311", baud_rate="115200", signal_freq=255)
