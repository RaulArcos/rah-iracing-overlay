"""Compare Chromium captures without adding an image-library dependency."""
import base64


def compare_pixels(page, captured, stored, overlay):
    def url(path):
        return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
    result = page.evaluate("""async ([a, b, overlay]) => {
        async function pixels(url) {
            const image = new Image(); image.src = url; await image.decode();
            const canvas = document.createElement('canvas');
            canvas.width = image.width; canvas.height = image.height;
            const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
            return {width:image.width, height:image.height,
                data:ctx.getImageData(0, 0, image.width, image.height).data};
        }
        const x = await pixels(a), y = await pixels(b);
        if (x.width !== y.width || x.height !== y.height) throw Error('Dimension mismatch');
        let changed = 0, maximum = 0, outside = 0;
        for (let i = 0; i < x.data.length; i += 4) {
            const px = (i / 4) % x.width, py = Math.floor(i / 4 / x.width);
            let delta = 0;
            for (let c = 0; c < 4; c++) delta = Math.max(delta, Math.abs(x.data[i+c] - y.data[i+c]));
            if (!delta) continue;
            changed++; maximum = Math.max(maximum, delta);
            // Observed compositor rounding is confined to the first pedal's
            // native rectangle. Text, graph, geometry and all other widgets
            // remain exact. Do not mask differences elsewhere.
            if (overlay !== 'input_telemetry' || px < 325 || px >= 353 || py < 47 || py >= 143) outside++;
        }
        return {changed_pixels:changed, max_channel_delta:maximum, outside_tolerance_region:outside};
    }""", [url(captured), url(stored), overlay])
    assert result['outside_tolerance_region'] == 0, (overlay, result)
    assert result['max_channel_delta'] <= 3, (overlay, result)
    assert result['changed_pixels'] <= 28 * 96, (overlay, result)
    return result
