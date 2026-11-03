import ARKit
import CoreImage
import UIKit

/// Renders a tiny picture of the face with ARKit's landmarks drawn on it, for the small corner
/// window on the Mac. Nothing is shown on the phone itself.
///
/// The camera is wide, so the picture is cropped around the face (smoothly, so it does not jump)
/// and the face fills the window. One job only: frame in, small JPEG out.
final class FacePreview {
    let size = CGSize(width: 120, height: 160)          // what the Mac receives
    private let work = CGSize(width: 360, height: 480)  // full camera view, before cropping
    private let context = CIContext()
    private var crop: CGRect?
    private let format: UIGraphicsImageRendererFormat = {
        let f = UIGraphicsImageRendererFormat()
        f.scale = 1
        return f
    }()

    func jpeg(frame: ARFrame, face: ARFaceAnchor?) -> Data? {
        guard let full = cameraImage(frame) else { return nil }
        let project = { (world: SIMD3<Float>) -> CGPoint in
            frame.camera.projectPoint(world, orientation: .portrait, viewportSize: self.work)
        }
        var mesh: [CGPoint] = []
        var eyes: [CGPoint] = []
        if let face {
            let vertices = face.geometry.vertices
            for i in stride(from: 0, to: vertices.count, by: 6) {
                mesh.append(project((face.transform * SIMD4<Float>(vertices[i], 1)).xyz3))
            }
            for eye in [face.leftEyeTransform, face.rightEyeTransform] {
                eyes.append(project((face.transform * eye).columns.3.xyz3))
            }
        }
        let area = cropArea(around: mesh)
        guard let piece = full.cropping(to: area) else { return nil }
        let scale = size.width / area.width
        let place = { (p: CGPoint) in CGPoint(x: (p.x - area.minX) * scale, y: (p.y - area.minY) * scale) }

        let image = UIGraphicsImageRenderer(size: size, format: format).image { ctx in
            UIImage(cgImage: piece).draw(in: CGRect(origin: .zero, size: size))
            let g = ctx.cgContext
            g.setFillColor(UIColor(red: 0.37, green: 0.75, blue: 0.75, alpha: 0.7).cgColor)
            for p in mesh.map(place) {
                g.fillEllipse(in: CGRect(x: p.x - 0.7, y: p.y - 0.7, width: 1.4, height: 1.4))
            }
            g.setFillColor(UIColor(red: 1.0, green: 0.40, blue: 0.59, alpha: 1).cgColor)
            for p in eyes.map(place) {
                g.fillEllipse(in: CGRect(x: p.x - 2.5, y: p.y - 2.5, width: 5, height: 5))
            }
        }
        return image.jpegData(compressionQuality: 0.5)
    }

    /// A 3:4 box around the face with room to spare, eased towards each new position.
    /// Without a face it eases back to the whole camera view.
    private func cropArea(around points: [CGPoint]) -> CGRect {
        var target = CGRect(origin: .zero, size: work)
        if points.count > 10 {
            let xs = points.map(\.x), ys = points.map(\.y)
            let box = CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)
            let height = min(work.height, max(box.height * 1.8, box.width * 1.8 * 4 / 3, 120))
            let width = height * 3 / 4
            var x = box.midX - width / 2, y = box.midY - height / 2
            x = min(max(0, x), work.width - width)
            y = min(max(0, y), work.height - height)
            target = CGRect(x: x, y: y, width: width, height: height)
        }
        let previous = crop ?? target
        let k: CGFloat = 0.3
        let eased = CGRect(x: previous.minX + (target.minX - previous.minX) * k,
                           y: previous.minY + (target.minY - previous.minY) * k,
                           width: previous.width + (target.width - previous.width) * k,
                           height: previous.height + (target.height - previous.height) * k)
        crop = eased
        return eased.integral
    }

    /// The camera image as the phone would display it in portrait, at the working size.
    private func cameraImage(_ frame: ARFrame) -> CGImage? {
        let buffer = frame.capturedImage
        let imageSize = CGSize(width: CVPixelBufferGetWidth(buffer), height: CVPixelBufferGetHeight(buffer))
        let normalize = CGAffineTransform(scaleX: 1 / imageSize.width, y: 1 / imageSize.height)
        let flip = CGAffineTransform(scaleX: -1, y: -1).translatedBy(x: -1, y: -1)
        let display = frame.displayTransform(for: .portrait, viewportSize: work)
        let toView = CGAffineTransform(scaleX: work.width, y: work.height)
        let image = CIImage(cvPixelBuffer: buffer)
            .transformed(by: normalize.concatenating(flip).concatenating(display).concatenating(toView))
        return context.createCGImage(image, from: CGRect(origin: .zero, size: work))
    }
}

private extension SIMD4 where Scalar == Float {
    var xyz3: SIMD3<Float> { SIMD3(x, y, z) }
}
