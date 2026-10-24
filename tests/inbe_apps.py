"""Opening Arcade in Inbe for the Shovey screen tests."""
import time


def open_arcade(driver, timeout=60):
    """Press Arcade in Inbe's Apps and wait until it opens. Inbe asks before
    it downloads an app: the download size with Download and Cancel, where
    the Download beside Cancel confirms, then Ready to open with Open."""
    driver.press(label='Apps', role='button')
    if not driver.find(label='Arcade', role='button', visible=True):
        driver.press(label='Find an app', role='text_field')
        driver.type('Arcade')
    driver.press(label='Arcade', role='button')
    deadline = time.monotonic() + timeout
    while driver.find(label='Find an app', role='text_field', visible=True):
        assert time.monotonic() < deadline, 'Arcade did not open: ' + ', '.join(driver.labels())
        cancel = driver.find(label='Cancel', role='button', visible=True)
        if cancel:
            downloads = driver.find(label='Download', role='button', visible=True)
            nearest = min(range(len(downloads)), key=lambda at: abs(downloads[at]['y'] - cancel[0]['y']))
            driver.press(label='Download', role='button', visible=True, index=nearest)
        elif driver.find(label='Ready to open', role='text', visible=True):
            driver.press(label='Open', role='button', visible=True)
        time.sleep(0.1)
